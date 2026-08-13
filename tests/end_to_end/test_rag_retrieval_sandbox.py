from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.knowledge.application.ports import IndexedChunk, IndexedSource
from qq_time_agent.modules.knowledge.contracts import build_index_version
from qq_time_agent.modules.knowledge.domain.chunking import CHUNKER_VERSION
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.knowledge.infrastructure.tables import KnowledgeSourceRow
from qq_time_agent.modules.retrieval.application.service import HybridRetrievalService
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]

EVALUATION_SET = (
    ("星河计划的报价在什么时候截止", "星河计划的供应商报价截止时间为周五下午五点。"),
    ("林澄负责哪个项目", "林澄是远帆迁移项目的联络负责人。"),
    ("蓝桥会议在哪个房间", "蓝桥复盘会议安排在海棠会议室。"),
    ("云杉合同编号是什么", "云杉采购合同编号是 YS-2048。"),
    ("北斗演示需要准备什么", "北斗产品演示前需要准备离线数据包和备用投影线。"),
    ("橙湾测试窗口是几点", "橙湾发布测试窗口为周三晚上八点到十点。"),
    ("青禾客户偏好哪种报告", "青禾客户偏好一页式周报并突出风险项。"),
    ("白鹭报销由谁审核", "白鹭差旅报销由财务同事沈岚审核。"),
    ("松涛培训什么时候开始", "松涛安全培训在九月十二日上午九点开始。"),
    ("晨曦项目的预算上限", "晨曦原型项目预算上限为十二万元。"),
    ("远山仓库收货时间", "远山仓库工作日收货时间为上午十点至下午四点。"),
    ("银杏文档存放位置", "银杏交付文档存放在团队共享盘的发布目录。"),
    ("赤霞联系人电话后四位", "赤霞供应商联系人电话后四位是 7316。"),
    ("清泉项目使用哪个数据库", "清泉分析项目确定使用 PostgreSQL 数据库。"),
    ("海盐评审要邀请谁", "海盐设计评审需要邀请产品、研发和无障碍顾问。"),
    ("梧桐设备保修到期日", "梧桐测试设备保修在十一月三十日到期。"),
    ("月桂样品寄到哪里", "月桂样品应寄到研发园区西门收件处。"),
    ("珊瑚接口限流是多少", "珊瑚服务接口限流为每分钟六百次请求。"),
    ("风铃活动主色是什么", "风铃活动视觉主色确定为深海蓝。"),
    ("岩兰巡检周期", "岩兰机房巡检周期为每两周一次。"),
    ("竹影备份保留多久", "竹影环境的增量备份保留二十八天。"),
    ("琥珀报告交给谁", "琥珀可用性报告交给项目经理周屿。"),
    ("雪松故障升级时限", "雪松服务严重故障需要在十五分钟内升级。"),
    ("荷风版本冻结日期", "荷风移动端版本在十月十八日冻结。"),
)


async def test_fixed_deidentified_hybrid_retrieval_recall_at_10() -> None:
    config = load_runtime_config()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlKnowledgeRepository(sessions)
    embeddings = OllamaEmbeddingAdapter(config.ollama, timeout_seconds=120)
    prefix = f"eval:{uuid4()}"
    refs = tuple(f"{prefix}:{index}" for index in range(len(EVALUATION_SET)))
    documents = tuple(document for _, document in EVALUATION_SET)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    try:
        batch = await embeddings.embed(documents, config.ollama.model, config.ollama.dimensions)
        for index, (source_ref, document, vector) in enumerate(
            zip(refs, documents, batch.vectors, strict=True)
        ):
            await repository.replace_active(
                IndexedSource(
                    uuid4(),
                    source_ref,
                    "OWNER_NOTE",
                    "v1",
                    now,
                    "T2",
                    {"eval": "fixed-deidentified-v1"},
                    CHUNKER_VERSION,
                    build_index_version(
                        config.ollama.index_version,
                        batch.model_id,
                        batch.model_digest,
                        batch.dimensions,
                    ),
                    batch.model_id,
                    batch.model_digest,
                    batch.dimensions,
                    (IndexedChunk(uuid4(), 0, document, f"eval-{index}", vector),),
                )
            )
        retrieval = HybridRetrievalService(
            repository,
            embeddings,
            config.ollama.model,
            config.ollama.dimensions,
            config.ollama.index_version,
            config.rag_vector_weight,
            config.rag_lexical_weight,
            30,
        )
        hits = 0
        reciprocal_ranks = 0.0
        for expected, (query, _) in zip(refs, EVALUATION_SET, strict=True):
            results = await retrieval.retrieve(
                query, RetrievalFilters(source_types=("OWNER_NOTE",)), 10
            )
            ranked = tuple(item.source_ref for item in results)
            if expected in ranked:
                hits += 1
                reciprocal_ranks += 1 / (ranked.index(expected) + 1)
        recall_at_10 = hits / len(EVALUATION_SET)
        mrr_at_10 = reciprocal_ranks / len(EVALUATION_SET)
        print(f"fixed-deidentified-v1 recall@10={recall_at_10:.3f} mrr@10={mrr_at_10:.3f}")
        assert recall_at_10 >= 0.85
    finally:
        for source_ref in refs:
            await repository.delete_source(source_ref)
        async with sessions.begin() as session:
            await session.execute(
                delete(KnowledgeSourceRow).where(KnowledgeSourceRow.source_ref.like(f"{prefix}%"))
            )
        await embeddings.close()
        await engine.dispose()
