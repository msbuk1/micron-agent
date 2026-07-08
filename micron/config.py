"""Configuration management for micron agent.

Handles loading and merging configuration from multiple sources:
- YAML file (micron.yaml)
- Environment variables
- CLI arguments
- Default values

Provides a unified Config class that validates and merges all sources.
"""
import os
from pathlib import Path
from typing import Optional, Any
import yaml


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
        self.config_path = Path(config_path) if config_path else None
        
        # Load from all sources
        self._config = self._load_all()
        
        # Validate
        self._validate()
    
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
        
        # 3. Override with environment variables
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
        }
        
        for env_var, config_key in env_mappings.items():
            full_var = f"{self.env_prefix}_{env_var}"
            if full_var in os.environ:
                # Try to convert to appropriate type
                value = os.environ[full_var]
                
                # Convert numeric values
                if config_key in ["temperature", "max_tokens", "max_tool_iterations", "port"]:
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
    
    def to_dict(self) -> dict:
        """Get full configuration as dictionary."""
        return self._config.copy()
    
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