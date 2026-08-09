"""Error handling utilities for micron tools.

Provides consistent error handling across all built-in tools.
"""


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
    if "FileNotFoundError" in error_type or "FileNotFound" in str(error):
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
