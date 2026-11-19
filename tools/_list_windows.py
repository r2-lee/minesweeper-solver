"""临时诊断脚本：列出当前所有可见顶层窗口（pid / 类名 / 标题 / owner）。"""

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32

rows = []
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def _callback(hwnd, _lparam):
    if not user32.IsWindowVisible(hwnd):
        return True
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, length + 1)
    if not title.value:
        return True
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    owner = user32.GetWindow(hwnd, 4)  # GW_OWNER
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    rows.append(
        (
            pid.value,
            cls.value,
            title.value,
            "owner={}".format(owner),
            "({},{})-({},{})".format(rect.left, rect.top, rect.right, rect.bottom),
        )
    )
    return True


user32.EnumWindows(EnumProc(_callback), 0)
for row in rows:
    print("pid={:<6} class={:<28} title={!r:<40} {} {}".format(*row))
print("共 {} 个可见窗口".format(len(rows)))
