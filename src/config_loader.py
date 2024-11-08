import typing

import yaml


class YamlConfig:
    def __init__(self, config_file_path: str) -> None:
        with open(config_file_path, "r", encoding="utf-8") as config_file:
            self.config = yaml.safe_load(config_file)

        self.config_file_path = config_file_path

    def get_field(
        self, path: str, default: typing.Any = None, required: bool = True
    ) -> typing.Any:
        value = self.config

        for part in path.split("."):
            if value is None or part not in value:
                if required and default is None:
                    raise KeyError(
                        f"Config option '{path}' not found in config file '{self.config_file_path}'"
                    )
                return default

            value = value.get(part)

        if value is None:
            value = default

        return value
