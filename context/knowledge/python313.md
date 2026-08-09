# Python 3.13 Release Notes

Python 3.13 was released on October 7, 2024. Key features include:

- **Experimental Free-threaded Mode**: PEP 703 - optional no-GIL builds
- **Improved Interactive Interpreter**: Built on PyREPL with syntax highlighting and multi-line editing
- **Improved Error Messages**: Better context and suggestions for common mistakes
- **New `dbm.sqlite3` Backend**: SQLite-based storage for the dbm module
- **Deprecation Warnings**: Various legacy modules now emit deprecation warnings

## Performance Improvements

- Faster startup time
- Reduced memory usage for certain workloads
- Improved JIT compiler (experimental)

## New Features

- `typing.TypeIs` for type narrowing
- `asyncio.eager_task_factory` for eager task execution
- `pathlib.Path.walk()` improvements
- New `os.process_cpu_count()` function