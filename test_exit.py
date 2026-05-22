import subprocess
from pathlib import Path
from config import get_src_basedir



base_dir = Path(get_src_basedir())
exit_script = base_dir / "exit_kiosk.sh"
subprocess.run([str(exit_script)], check=False) 
