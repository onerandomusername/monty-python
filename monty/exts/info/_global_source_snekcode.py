"""
Do not import this file.

NOTE: THIS RUNS ON PYTHON 3.10
"""

# exit codes:
# 0: success
# 1: indeterminate error
# 2: module not resolvable
# 3: attribute does not exist
# 4: invalid characters, not a valid object path
# 5: dynamically created object
# 6: is a builtin object, prints module name
# 7: invalid metadata
# 8: unsupported package (does not use github)

if __name__ == "__main__":
    import importlib
    import importlib.metadata
    import inspect
    import pathlib
    import pkgutil
    import sys

    # establish the object itself
    object_name = "REPLACE_THIS_STRING_WITH_THE_OBJECT_NAME"
    try:
        src = pkgutil.resolve_name(object_name)
    except ModuleNotFoundError:
        sys.exit(2)
    except AttributeError:
        sys.exit(3)
    except ValueError:
        sys.exit(4)
    except Exception:
        raise

    # used to be able to slice code to ignore import side-effects
    print("#" * 80)

    # get the source of the object
    try:
        filename = inspect.getsourcefile(src)
    except TypeError:
        sys.exit(5)
    if not inspect.ismodule(src):
        lines, first_line_no = inspect.getsourcelines(src)
        lines_extension = f"#L{first_line_no}-L{first_line_no+len(lines)-1}"
    else:
        lines_extension = ""

    module_name = src.__name__ if inspect.ismodule(src) else src.__module__
    top_module_name = module_name.split(".", 1)[0]

    # determine the actual file name
    filename = str(
        pathlib.Path(filename).relative_to(
            pathlib.Path(inspect.getsourcefile(importlib.import_module(top_module_name))).parent.parent
        )
    )

    # get the version and link to the source of the module
    if top_module_name in sys.stdlib_module_names:
        if top_module_name in sys.builtin_module_names:
            print(module_name)
            sys.exit(6)
        # handle the object being part of the stdlib
        import platform

        python_version = f"python{platform.python_version().rsplit('.', 1)[0]}/"
        if filename.startswith(python_version):
            filename = filename.split("/", 1)[-1]
        url = f"https://github.com/python/cpython/blob/v{platform.python_version()}/Lib/{filename}{lines_extension}"
    else:
        # assume that the source is github
        try:
            metadata = importlib.metadata.metadata(top_module_name)
        except importlib.metadata.PackageNotFoundError:
            print(f"Sorry, I can't find the metadata for `{module_name}`.")
            sys.exit(7)
        # print(metadata.keys())
        version = metadata["Version"]
        for url in [metadata.get("Home-page"), *metadata.json["project_url"]]:
            url = url.split(",", 1)[-1].strip()
            if url.startswith(("https://github.com/", "http://github.com/")):
                break
        else:
            print("This package isn't supported right now.")
            sys.exit(8)
        if top_module_name != "arrow":
            version = f"v{version}"
        url += f"/blob/{version}/{filename}{lines_extension}"
    print(url)
