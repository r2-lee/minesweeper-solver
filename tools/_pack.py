"""把要部署到 201 的源码打进 adaptive_deploy.tar.gz（不带 runtime/site-packages）。"""

import os
import tarfile

SKIP_DIRS = {"runtime", "site-packages", "__pycache__", ".git", "backup"}
NAMES = ["minesweeper", "tests", "tools", "native", "docs",
         "run_tests.py", "mine.py", "PyStand.int", "README.md"]


def main() -> None:
    path = "adaptive_deploy.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name in NAMES:
            if os.path.isfile(name):
                tar.add(name, name)
                continue
            for root, dirs, files in os.walk(name):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for item in files:
                    if item.endswith((".pyc", ".pyo")):
                        continue
                    full = os.path.join(root, item)
                    tar.add(full, full)
    print(path, os.path.getsize(path))


if __name__ == "__main__":
    main()
