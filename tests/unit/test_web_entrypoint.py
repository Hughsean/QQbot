from unittest.mock import patch

import uvicorn

from qq_time_agent.bootstrap import web


def test_web_entrypoint_preserves_windows_selector_policy_for_psycopg() -> None:
    with (
        patch.object(web, "configure_event_loop_policy") as configure,
        patch.object(web, "configure_logging"),
        patch.object(web, "load_runtime_config") as load,
        patch.object(web, "build_app", return_value=(object(), object(), ())),
        patch.object(uvicorn, "run") as run,
    ):
        load.return_value.app.listen_host = "127.0.0.1"
        load.return_value.app.listen_port = 8000
        web.main()

    configure.assert_called_once_with()
    assert run.call_args.kwargs["loop"] == "none"
    assert run.call_args.kwargs["access_log"] is False
