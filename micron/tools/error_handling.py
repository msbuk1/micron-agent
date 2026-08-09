"""Error handling utilities for micron tools.

Provides consistent error handling across all built-in tools.
"""
from typing import Any


class ToolError(Exception):
    """Base exception for tool-related errors."""
    
    def __init__(self, message: str, tool_name: str = "unknown"):
        self.tool_name = tool_name
        self.message = message
        super().__init__(f"[{tool_name}] {message}")
    
    def to_dict(self) -> dict:
        """Convert error to dictionary format."""
        return {
            "type": "tool_error",
            "name": self.tool_name,
            "error": self.message
        }


def handle_error(tool_name: str, error: Exception, context: str = "") -> str:
    """Standardize error handling across all tools.
    
    Args:
        tool_name: Name of the tool that encountered the error
        error: The exception that was raised
        context: Additional context about what was happening
        
    Returns:
        Formatted error message string
    """
    error_type = type(error).__name__
    
    # Format error message based on error type
    if isinstance(error, ToolError):
        return f"Error: {error.message}"
    
    elif "FileNotFoundError" in error_type or "FileNotFound" in str(error):
        return f"Error: File not found - {context or 'the specified file does not exist'}"
    
    elif "PermissionError" in error_type or "Permission" in str(error):
        return f"Error: Permission denied - {context or 'you do not have permission to perform this operation'}"
    
    elif "Timeout" in error_type or "timeout" in str(error).lower():
        return f"Error: Operation timed out - {context or 'the operation took too long'}"
    
    elif "ValueError" in error_type or "Invalid" in str(error):
        return f"Error: Invalid input - {context or str(error)}"
    
    elif "TypeError" in error_type:
        return f"Error: Type mismatch - {context or str(error)}"
    
    elif "OSError" in error_type or "IOError" in error_type:
        return f"Error: I/O error - {context or str(error)}"
    
    else:
        # Generic error handling
        msg = str(error)
        if context:
            msg = f"{context}: {msg}"
        return f"Error: {msg}"


def success(message: str) -> str:
    """Create a success message.
    
    Args:
        message: The success message
        
    Returns:
        Formatted success message
    """
    return f"Success: {message}"


def format_tool_result(result: Any, tool_name: str = "unknown") -> dict:
    """Format tool result in a consistent way.
    
    Args:
        result: The result to format
        tool_name: Name of the tool
        
    Returns:
        Dictionary with type and content
    """
    if isinstance(result, str):
        return {
            "type": "text",
            "content": result
        }
    elif isinstance(result, list):
        return {
            "type": "list",
            "items": result
        }
    elif isinstance(result, dict) and "type" in result:
        return result
    else:
        return {
            "type": "text",
            "content": str(result)
        }


# Example usage in a tool:
# try:
#     result = some_operation()
#     return format_tool_result(result, "my_tool")
# except Exception as e:
#     return handle_error("my_tool", e, "while processing file")
