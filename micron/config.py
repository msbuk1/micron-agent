"""Configuration management for micron agent.

Handles loading and merging configuration from multiple sources:
- YAML file (micron.yaml)
- Environment variables
- CLI arguments
- Default values

Provides a unified Config class that validates and merges all sources.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any
import yaml


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge ``overlay`` into ``base`` (overlay wins).

    Unlike ``dict.update``, nested dicts are merged key-by-key so an
    ``auth.yaml`` containing only ``providers.openrouter.api_key`` doesn't
    clobber the other provider settings from ``micron.yaml``.
    """
    for key, value in overlay.items():
        if (
            isinstance(value, dict)
            and isinstance(base.get(key), dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


@dataclass
class AuthConfig:
    """Authentication configuration."""
    enabled: bool = False
    api_key_required: bool = False
    api_key_env_var: str = "MICRON_API_KEY"


@dataclass(frozen=True)
class RuntimeConfig:
    """Typed viewport over Config — replaces untyped resolve_runtime dict."""
    provider: str
    model: str | None
    api_key: str | None
    base_url: str | None
    temperature: float
    max_tokens: int
    max_tool_iterations: int
    workdir: Path
    context_dir: Path
    firecrawl_url: str | None
    host: str
    port: int
    n_threads: int
    n_ctx: int
    n_gpu_layers: int

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_tool_iterations": self.max_tool_iterations,
            "workdir": str(self.workdir),
            "context_dir": str(self.context_dir),
            "firecrawl_url": self.firecrawl_url,
            "host": self.host,
            "port": self.port,
            "n_threads": self.n_threads,
            "n_ctx": self.n_ctx,
            "n_gpu_layers": self.n_gpu_layers,
        }

    def for_agent(self) -> dict:
        return {
            "context_dir": str(self.context_dir),
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_tool_iterations": self.max_tool_iterations,
        }

    def for_backend(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "n_threads": self.n_threads,
            "n_gpu_layers": self.n_gpu_layers,
            "n_ctx": self.n_ctx,
        }

    def replace(self, **overrides) -> "RuntimeConfig":
        import dataclasses

        return dataclasses.replace(self, **overrides)

    @classmethod
    def fake(cls, tmp_path: Path, **overrides) -> "RuntimeConfig":
        base = dict(
            provider="fake",
            model="fake-model",
            api_key=None,
            base_url=None,
            temperature=0.1,
            max_tokens=10000,
            max_tool_iterations=10,
            workdir=Path(tmp_path),
            context_dir=Path(tmp_path) / "context",
            firecrawl_url="http://localhost:3002",
            host="0.0.0.0",
            port=8000,
            n_threads=8,
            n_ctx=8192,
            n_gpu_layers=0,
        )
        base.update(overrides)
        # coerce Path
        if isinstance(base["workdir"], str):
            base["workdir"] = Path(base["workdir"])
        if isinstance(base["context_dir"], str):
            base["context_dir"] = Path(base["context_dir"])
        return cls(**base)


class Config:
    """Unified configuration for micron agent."""
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        env_prefix: str = "MICRON",
    ):
        """Initialize configuration from multiple sources.
        
        Priority order (highest to lowest):
        1. Environment variables
        2. CLI arguments (passed directly to methods)
        3. YAML config file
        4. Default values
        
        Args:
            config_path: Path to YAML config file
            env_prefix: Prefix for environment variables (default: MICRON)
        """
        self.env_prefix = env_prefix
        self.config_path = self._resolve_config_path(config_path)
        self.auth_path = None  # set during _load_all after config_path resolves

        # Load from all sources
        self._config = self._load_all()

        # Validate
        self._validate()

        # Populate env vars consumed by tools and other modules.
        # Replaces the side-effect that __main__.load_config used to own.
        self._apply_env_vars()
    
    def _resolve_config_path(self, config_path: Optional[str]) -> Optional[Path]:
        """Resolve the config file path, auto-discovering micron.yaml if not given."""
        if config_path:
            return Path(config_path)
        candidates = [
            Path.cwd() / "micron.yaml",
            Path(__file__).parent.parent / "micron.yaml",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _resolve_auth_path(self, config_path: Optional[Path]) -> Optional[Path]:
        """Resolve auth.yaml next to micron.yaml (secrets, never committed)."""
        if config_path:
            return config_path.parent / "auth.yaml" if (config_path.parent / "auth.yaml").exists() else None
        candidates = [
            Path.cwd() / "auth.yaml",
            Path(__file__).parent.parent / "auth.yaml",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _load_all(self) -> dict:
        """Load configuration from all sources."""
        config = {}

        # 1. Start with defaults
        config.update(self._get_defaults())

        # 2. Load from YAML file if exists
        if self.config_path and self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    file_config = yaml.safe_load(f) or {}
                config.update(file_config)
            except Exception as e:
                print(f"[config] Warning: Could not load {self.config_path}: {e}")

        # 3. Merge secrets from auth.yaml (gitignored) over micron.yaml so
        #    placeholders in the tracked file get replaced by real keys.
        self.auth_path = self._resolve_auth_path(self.config_path)
        if self.auth_path and self.auth_path.exists():
            try:
                with open(self.auth_path) as f:
                    auth_config = yaml.safe_load(f) or {}
                _deep_merge(config, auth_config)
            except Exception as e:
                print(f"[config] Warning: Could not load {self.auth_path}: {e}")

        # 4. Override with environment variables
        config.update(self._load_env_vars())

        return config
    
    def _get_defaults(self) -> dict:
        """Get default configuration values."""
        return {
            # Context and working directory
            "context_dir": "context",
            "workdir": str(Path.cwd()),
            
            # Provider settings
            "default_provider": "llamacpp",
            "temperature": 0.1,
            "max_tokens": 10000,
            "max_tool_iterations": 10,
            
            # Write confirmation
            # "ask" (default) — prompt in TUI; "allow" — execute writes without prompting;
            # "deny" — reject all write tools silently.
            "auto_confirm_writes": "ask",

            # Server settings
            "host": "0.0.0.0",
            "port": 8000,
            
            # Firecrawl settings
            "firecrawl_url": "http://localhost:3002",
            
            # Provider configurations
            "providers": {
                "llamacpp": {
                    "model": "models/MiniCPM5-1B-Q8_0.gguf",
                    "n_threads": 8,
                    "n_gpu_layers": 0,
                    "n_ctx": 8192,
                    "chat_format": "chatml",
                },
                "openrouter": {
                    "api_key": "",
                    "base_url": "https://openrouter.ai/api/v1",
                    "model": "openrouter/auto",
                },
                "lmstudio": {
                    "api_key": "no_key",
                    "base_url": "http://localhost:1234/v1",
                    "model": "mistralai/ministral-3-3b",
                    "chat_format": "gemmaml",
                },
                "ollama": {
                    "base_url": "http://localhost:11434",
                    "model": "llama3",
                    "chat_format": "chatml",
                },
                "openai": {
                    "api_key": "",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini",
                    "chat_format": "chatml",
                },
            },
        }
    
    def _load_env_vars(self) -> dict:
        """Load configuration from environment variables."""
        env_config = {}
        
        # Map environment variables to config keys
        env_mappings = {
            "PROVIDER": "default_provider",
            "CONTEXT_DIR": "context_dir",
            "WORKDIR": "workdir",
            "TEMPERATURE": "temperature",
            "MAX_TOKENS": "max_tokens",
            "MAX_TOOL_ITERATIONS": "max_tool_iterations",
            "HOST": "host",
            "PORT": "port",
            "FIRECRAWL_URL": "firecrawl_url",
            "AUTO_CONFIRM_WRITES": "auto_confirm_writes",
        }
        
        for env_var, config_key in env_mappings.items():
            full_var = f"{self.env_prefix}_{env_var}"
            if full_var in os.environ:
                # Try to convert to appropriate type
                value = os.environ[full_var]
                
                # Convert numeric values
                if config_key in ["max_tokens", "max_tool_iterations", "port"]:
                    try:
                        value = int(value)
                    except ValueError:
                        pass
                elif config_key == "temperature":
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                
                env_config[config_key] = value
        
        # Handle provider-specific environment variables
        for provider in ["llamacpp", "openrouter", "lmstudio", "ollama", "openai"]:
            api_key_var = f"{self.env_prefix}_API_KEY_{provider.upper()}"
            base_url_var = f"{self.env_prefix}_BASE_URL_{provider.upper()}"
            model_var = f"{self.env_prefix}_MODEL_{provider.upper()}"
            
            provider_config = {}
            
            if api_key_var in os.environ:
                provider_config["api_key"] = os.environ[api_key_var]
            if base_url_var in os.environ:
                provider_config["base_url"] = os.environ[base_url_var]
            if model_var in os.environ:
                provider_config["model"] = os.environ[model_var]
            
            if provider_config:
                if "providers" not in env_config:
                    env_config["providers"] = {}
                env_config["providers"][provider] = provider_config
        
        # Handle default provider override
        provider_var = f"{self.env_prefix}_PROVIDER"
        if provider_var in os.environ:
            env_config["default_provider"] = os.environ[provider_var]
        
        return env_config
    
    def _validate(self):
        """Validate configuration."""
        # Ensure providers exist
        if "providers" not in self._config:
            self._config["providers"] = {}
        
        # Ensure default provider exists
        if "default_provider" not in self._config:
            self._config["default_provider"] = "llamacpp"
        
        if self._config["default_provider"] not in self._config["providers"]:
            print(f"[config] Warning: Default provider '{self._config['default_provider']}' not configured")

    def _apply_env_vars(self) -> None:
        """Set env vars consumed by tools and other modules.

        Only sets a var if it isn't already in the environment, so explicit
        shell exports always win.
        """
        workdir = self.get("workdir")
        if workdir and "MICRON_WORKDIR" not in os.environ:
            os.environ["MICRON_WORKDIR"] = workdir

        context_dir = self.get("context_dir")
        if context_dir:
            ctx_path = Path(context_dir)
            if not ctx_path.is_absolute():
                ctx_path = Path(__file__).parent.parent / context_dir
            if "MICRON_CONTEXT_DIR" not in os.environ:
                os.environ["MICRON_CONTEXT_DIR"] = str(ctx_path)

        provider = self.get("default_provider")
        if provider and "MICRON_PROVIDER" not in os.environ:
            os.environ["MICRON_PROVIDER"] = provider

        firecrawl = self.get("firecrawl_url")
        if firecrawl and "FIRECRAWL_URL" not in os.environ:
            os.environ["FIRECRAWL_URL"] = firecrawl

    def runtime(
        self,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> RuntimeConfig:
        """Typed viewport over Config — hides dict hoisting."""
        provider = provider_override or self.get("default_provider")
        prov_cfg = self.get_provider_config(provider)
        workdir = Path(self.get("workdir", str(Path.cwd()))).resolve()
        ctx_raw = self.get("context_dir", "context")
        ctx_path = Path(ctx_raw)
        if not ctx_path.is_absolute():
            ctx_path = (Path(__file__).parent.parent / ctx_path).resolve()
        else:
            ctx_path = ctx_path.resolve()
        return RuntimeConfig(
            provider=provider,
            model=model_override or prov_cfg.get("model"),
            api_key=prov_cfg.get("api_key"),
            base_url=prov_cfg.get("base_url"),
            temperature=float(self.get("temperature", 0.1)),
            max_tokens=int(self.get("max_tokens", 10000)),
            max_tool_iterations=int(self.get("max_tool_iterations", 10)),
            workdir=workdir,
            context_dir=ctx_path,
            firecrawl_url=self.get("firecrawl_url"),
            host=self.get("host", "0.0.0.0"),
            port=int(self.get("port", 8000)),
            n_threads=int(prov_cfg.get("n_threads", 8)),
            n_gpu_layers=int(prov_cfg.get("n_gpu_layers", 0)),
            n_ctx=int(prov_cfg.get("n_ctx", 8192)),
        )

    def resolve_runtime(
        self,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> dict:
        """Return a flat dict with all settings needed to build an agent + backend.

        Hoists the selected provider's config (model, api_key, base_url,
        n_threads, …) to the top level so ``create_agent_and_logger`` can
        read everything without knowing about the providers dict.
        Kept for compat — delegates to runtime().as_dict().
        """
        return self.runtime(provider_override, model_override).as_dict()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key.
        
        Supports nested keys with dot notation (e.g., "providers.lmstudio.base_url").
        """
        if "." in key:
            # Handle nested keys
            parts = key.split(".")
            value = self._config
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return default
            return value
        
        return self._config.get(key, default)
    
    def get_provider_config(self, provider_name: Optional[str] = None) -> dict:
        """Get configuration for a specific provider."""
        provider_name = provider_name or self.get("default_provider")
        return self.get("providers", {}).get(provider_name, {})
    
    def get_rate_limits(self) -> dict:
        """Get rate limiting configuration.
        
        Returns:
            Dictionary with rate limit settings
        """
        return {
            "chat_requests_per_minute": int(self._config.get("rate_limits", {}).get("chat_requests_per_minute", 60)),
            "enabled": self._config.get("rate_limits", {}).get("enabled", False),
        }
    
    def get_resource_limits(self) -> dict:
        """Get resource limit configuration.
        
        Returns:
            Dictionary with resource limit settings
        """
        return {
            "cpu_time_limit": int(self._config.get("resource_limits", {}).get("cpu_time_limit", 30)),
            "max_output_size": int(self._config.get("resource_limits", {}).get("max_output_size", 15000)),
            "enabled": self._config.get("resource_limits", {}).get("enabled", False),
        }
    
    def get_authentication(self) -> AuthConfig:
        """Get authentication configuration.
        
        Returns:
            AuthConfig dataclass with authentication settings
        """
        auth_config = self._config.get("authentication", {})
        return AuthConfig(
            enabled=auth_config.get("enabled", False),
            api_key_required=auth_config.get("api_key_required", False),
            api_key_env_var=auth_config.get("api_key_env_var", "MICRON_API_KEY"),
        )
    
    def is_valid_api_key(self, provided_key: Optional[str] = None) -> bool:
        """Check if provided API key is valid.
        
        Args:
            provided_key: API key from request header/query
            
        Returns:
            True if valid or auth disabled, False if invalid
        """
        auth = self.get_authentication()
        
        # Auth disabled — always valid
        if not auth.enabled:
            return True
        
        # API key not required — always valid
        if not auth.api_key_required:
            return True
        
        # No key provided — invalid
        if not provided_key:
            return False
        
        # Get expected key from environment
        expected_key = os.getenv(auth.api_key_env_var, "")
        if not expected_key:
            # No key configured — deny access
            return False
        
        # Constant-time comparison to prevent timing attacks
        import hmac
        return hmac.compare_digest(provided_key, expected_key)
    
    def to_dict(self) -> dict:
        """Return raw config dict (copy)."""
        import copy

        return copy.deepcopy(self._config)

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access."""
        return self.get(key)
    
    def __repr__(self) -> str:
        """String representation (without sensitive data)."""
        config = self.to_dict()
        # Remove API keys
        if "providers" in config:
            for provider in config["providers"].values():
                if "api_key" in provider:
                    provider["api_key"] = "***REDACTED***"
        return f"Config({config})"


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file and environment.
    
    Args:
        config_path: Path to YAML config file (optional)
        
    Returns:
        Config instance
    """
    return Config(config_path=config_path)


# Example usage
if __name__ == "__main__":
    # Load configuration
    config = load_config("micron.yaml")
    
    print("Configuration loaded successfully!")
    print(f"Default provider: {config.get('default_provider')}")
    print(f"Workdir: {config.get('workdir')}")
    print(f"Providers: {list(config.get('providers', {}).keys())}")