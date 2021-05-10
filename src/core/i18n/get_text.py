# -*- coding: utf-8 -*-
import argparse
import pathlib
import re
import sys
from datetime import datetime
from inspect import cleandoc

from yaml import load
from yaml import Loader


def main(directory, target_filename, patch):  # noqa: too-many-locals
    _defaults = {}
    if patch:
        _defaults = load(
            open(pathlib.Path.cwd() / patch, mode="r", encoding="utf-8").read(),
            Loader=Loader,
        )

    to_check = []
    for path in pathlib.Path(directory).rglob("*.py"):
        to_check.append(path)
        print("Found", path)

    strings = []
    with open(
        pathlib.Path.cwd() / target_filename,
        "w+",
        encoding="utf-8",
        errors="ignore",
    ) as target:
        target.write(
            cleandoc(
                f"""
        # NOTE: This is an automatically generated file.
        # Generated on {datetime.now()}
        # With {' '.join(sys.argv)}
        """
            )
        )
        target.write("\n\n")
        for file_name in to_check:
            with open(file_name, "r", encoding="utf-8", errors="ignore") as file:
                t = f"# {file_name}\n"
                found_any = False

                for match in re.findall(
                    r'(?:_|I18n.get_string)\(\s*["\'](.+?)["\'](?:,\s*((?:.|\s)+?))?\s*\)',
                    file.read(),
                ):
                    string, params = match
                    if string in strings:
                        continue

                    comment = ""
                    if params != "":
                        comment = "  # " + ", ".join(re.findall(r"(\w+)=", params))

                    found_any = True
                    strings.append(string)

                    default = _defaults.get(string, "")
                    formatted_string = f'"{default}"'
                    if "\n" in default:
                        default = "\n    ".join(default.split("\n"))
                        formatted_string = f"|\n    {default}\n"

                    t += f"{string}: {formatted_string}{comment}\n"

                t += "\n"

                if found_any:
                    target.write(t)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find all i18n text")
    parser.add_argument("-d", "--directory", default=pathlib.Path.cwd(), action="store")
    parser.add_argument("-t", "--target", default="output.yml", action="store")
    parser.add_argument("-p", "--patch", default=None, action="store")

    args = parser.parse_args()
    main(args.directory, args.target, args.patch)
