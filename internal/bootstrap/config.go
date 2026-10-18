package bootstrap

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
	_ "time/tzdata"

	"github.com/joho/godotenv"

	"qqtimeagent/internal/platform/secret"
)

// Config is owned by the composition root and never passed to business modules.
type Config struct {
	Container     bool
	ListenHost    string
	ListenPort    int
	Database      DatabaseConfig
	OllamaURL     string
	OllamaModel   string
	Dimensions    int
	Timezone      string
	SigningKey    secret.Value
	EncryptionKey secret.Value
	QQ            QQConfig
}

type DatabaseConfig struct {
	Host     string
	Port     int
	Name     string
	User     string
	Password secret.Value
}

type QQConfig struct {
	AppID     secret.Value
	AppSecret secret.Value
	Owner     secret.Value
	Sandbox   bool
}

// LoadConfig is the sole environment entry point. Tests use ParseConfig directly.
func LoadConfig(path string) (Config, error) {
	values, err := godotenv.Read(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return Config{}, errors.New("invalid configuration file")
	}
	if values == nil {
		values = make(map[string]string)
	}
	for _, item := range os.Environ() {
		key, value, ok := strings.Cut(item, "=")
		if ok {
			values[key] = value
		}
	}
	return ParseConfig(values)
}

func ParseConfig(values map[string]string) (Config, error) {
	r := configReader{values: values}
	c := Config{
		Container:  r.boolean("APP_CONTAINER", false),
		ListenHost: r.text("APP_LISTEN_HOST", "127.0.0.1"),
		ListenPort: r.integer("APP_LISTEN_PORT", 8000, 1, 65535),
		Database: DatabaseConfig{
			Host:     r.text("DATABASE_HOST", "127.0.0.1"),
			Port:     r.integer("DATABASE_PORT", 5432, 1, 65535),
			Name:     r.text("DATABASE_NAME", "qq_time_agent"),
			User:     r.text("DATABASE_USER", "qq_time_agent"),
			Password: secret.New(r.text("DATABASE_PASSWORD", "")),
		},
		OllamaURL:     r.text("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
		OllamaModel:   r.text("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b"),
		Dimensions:    r.integer("RAG_EMBEDDING_DIMENSIONS", 1024, 1024, 1024),
		Timezone:      r.text("DEFAULT_TIMEZONE", "Asia/Shanghai"),
		SigningKey:    secret.New(r.text("APP_SIGNING_KEY", "")),
		EncryptionKey: secret.New(r.text("CREDENTIAL_ENCRYPTION_KEY", "")),
		QQ: QQConfig{
			AppID:     secret.New(r.text("QQ_BOT_APP_ID", "")),
			AppSecret: secret.New(r.text("QQ_BOT_SECRET", "")),
			Owner:     secret.New(r.text("OWNER_QQ_OPENID", "")),
			Sandbox:   r.boolean("QQ_BOT_SANDBOX", true),
		},
	}
	if r.err != nil {
		return Config{}, r.err
	}
	if err := c.validate(); err != nil {
		return Config{}, err
	}
	return c, nil
}

func (c Config) validate() error {
	if err := c.validateNetwork(); err != nil {
		return err
	}
	if _, err := time.LoadLocation(c.Timezone); err != nil {
		return errors.New("DEFAULT_TIMEZONE must be a valid IANA timezone")
	}
	if c.Database.Name == "" || c.Database.User == "" || c.OllamaModel == "" {
		return errors.New("database identity and embedding model must not be empty")
	}
	return nil
}

func (c Config) validateNetwork() error {
	if c.Container {
		return c.validateContainer()
	}
	u, err := localOrigin(c.OllamaURL)
	if err != nil {
		return err
	}
	for _, host := range []string{c.ListenHost, c.Database.Host, u.Hostname()} {
		ip := net.ParseIP(host)
		if ip == nil || !ip.IsLoopback() {
			return errors.New("local endpoints must use loopback IPs")
		}
	}
	return nil
}

func (c Config) validateContainer() error {
	if c.ListenHost != "0.0.0.0" || c.Database.Host != "postgres" ||
		c.Database.Port != 5432 || c.OllamaURL != "http://ollama:11434" {
		return errors.New("container requires exact private network endpoints")
	}
	return nil
}

func localOrigin(value string) (*url.URL, error) {
	u, err := url.Parse(value)
	if err != nil || u.Scheme != "http" || u.User != nil || u.RawQuery != "" ||
		u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return nil, errors.New("OLLAMA_BASE_URL must be a loopback HTTP origin")
	}
	return u, nil
}

func (c DatabaseConfig) ConnectionString() string {
	u := url.URL{Scheme: "postgres", Host: net.JoinHostPort(c.Host, strconv.Itoa(c.Port)),
		Path: "/" + c.Name, User: url.UserPassword(c.User, c.Password.Reveal())}
	q := u.Query()
	q.Set("sslmode", "disable")
	q.Set("timezone", "UTC")
	u.RawQuery = q.Encode()
	return u.String()
}

func (c Config) Address() string { return net.JoinHostPort(c.ListenHost, strconv.Itoa(c.ListenPort)) }

// Role validation avoids requiring unrelated Provider secrets for migrations/health.
func (c Config) requireDatabase() error {
	if !c.Database.Password.Present() {
		return fmt.Errorf("DATABASE_PASSWORD is required")
	}
	return nil
}
