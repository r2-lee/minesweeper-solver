"""临时诊断脚本：从 mine.exe 里抠出内嵌的 _pystand_static.int 文本。"""

import sys

path = sys.argv[1] if len(sys.argv) > 1 else "mine.exe"
offset = int(sys.argv[2]) if len(sys.argv) > 2 else 74100
length = int(sys.argv[3]) if len(sys.argv) > 3 else 4000

with open(path, "rb") as f:
    raw = f.read()

chunk = raw[offset : offset + length]
text = chunk.decode("utf-8", "replace")
print(text)
