"""Add Terminus-2's tmux dependency to the task's Docker build."""
import hashlib
import os
from pathlib import Path
import re

import yaml
from harbor.environments.docker.docker import DockerEnvironment


class TerminusDockerEnvironment(DockerEnvironment):
    @property
    def _docker_compose_paths(self):
        paths = super()._docker_compose_paths
        original = self.environment_dir / "Dockerfile"
        if self._use_prebuilt or not original.is_file():
            return paths

        network = os.environ.get("ADAPTABILITY_DOCKER_BUILD_NETWORK")
        build = {"network": network} if network else {}
        if self.environment_dir.name != "tests":
            text = original.read_text(encoding="utf-8").rstrip()
            final_stage = re.split(r"(?im)^\s*FROM\s+", text)[-1]
            users = re.findall(r"(?im)^\s*USER[ \t]+([^\r\n]+)", final_stage)
            restore_user = users[-1].strip() if users else "root"
            content = (
                text + "\n\nUSER root\n"
                "RUN command -v tmux >/dev/null 2>&1 || (apt-get update && "
                "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tmux && "
                "rm -rf /var/lib/apt/lists/*)\n"
                f"USER {restore_user}\n"
            )
            key = hashlib.sha256(content.encode()).hexdigest()
            dockerfile = Path(os.environ["ADAPTABILITY_DOCKER_TOOLING"]) / key / "Dockerfile"
            self._write_overlay(dockerfile, content)
            build["dockerfile"] = str(dockerfile)
        if not build:
            return paths
        compose = yaml.safe_dump({"services": {"main": {"build": build}}})
        key = hashlib.sha256(compose.encode()).hexdigest()
        directory = Path(os.environ["ADAPTABILITY_DOCKER_TOOLING"]) / key
        overlay = directory / "compose.yaml"
        self._write_overlay(overlay, compose)
        return [*paths, overlay]

    @staticmethod
    def _write_overlay(path, text):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
