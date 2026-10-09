from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Windows-only")
    import msvcrt
    read_fd, write_fd = os.pipe()
    handle = msvcrt.get_osfhandle(read_fd)
    os.set_handle_inheritable(handle, True)
    si = subprocess.STARTUPINFO(); si.lpAttributeList = {"handle_list": [handle]}
    code = (
        "import msvcrt,os,sys; "
        "h=int(sys.argv[1]); fd=msvcrt.open_osfhandle(h,os.O_RDONLY); "
        "d=os.read(fd,5); os.close(fd); sys.exit(0 if d==b'HELLO' else 9)"
    )
    try:
        try:
            child = subprocess.Popen([sys.executable, "-c", code, str(handle)], close_fds=True, startupinfo=si)
        finally:
            os.set_handle_inheritable(handle, False)
        os.close(read_fd); os.write(write_fd, b"HELLO"); os.close(write_fd)
        rc=child.wait(timeout=10)
        if rc != 0: raise SystemExit(f"inherited HANDLE probe failed: {rc}")
    finally:
        for fd in (read_fd, write_fd):
            try: os.close(fd)
            except OSError: pass
    print("SPRINT10 RAW HANDLE INHERITANCE: PASS")
    return 0

if __name__=="__main__": raise SystemExit(main())
