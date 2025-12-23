import docker
import time
import logging
import tarfile
import io
import base64
import os
from typing import Tuple, List, Optional, Dict

logger = logging.getLogger("Tools-Sandbox")

class DockerSandbox:
    def __init__(self, image: str = "python:3.9-slim"):
        self.client = docker.from_env()
        self.image = image
        self.container_name = "swarm_sandbox_runner"
        self.container = None

    def run_code(self, code: str) -> Tuple[str, str, List[Dict[str, str]]]:
        try:
            try:
                self.container = self.client.containers.get(self.container_name)
                if self.container.status != "running":
                    self.container.start()
            except docker.errors.NotFound:
                self.container = self.client.containers.run(
                    self.image,
                    detach=True,
                    tty=True,
                    name=self.container_name,
                    mem_limit="512m",
                    network_mode="none" 
                )
            
            wrapped_code = self._wrap_code_with_plot_saving(code)
            self._write_file_to_container("/tmp", "script.py", wrapped_code)
            
            exec_result = self.container.exec_run("python -u /tmp/script.py")
            stdout = exec_result.output.decode("utf-8", errors="replace")
            stderr = stdout if exec_result.exit_code != 0 else ""
            
            images = self._extract_image_from_container("/tmp/plot.png")
            return stdout, stderr, images
            
        except Exception as e:
            return "", f"System Error: {str(e)}", []

    def _write_file_to_container(self, dest_dir: str, filename: str, content: str):
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            data = content.encode('utf-8')
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(data)
            tarinfo.mtime = time.time()
            tar.addfile(tarinfo, io.BytesIO(data))
        tar_stream.seek(0)
        self.container.put_archive(path=dest_dir, data=tar_stream)

    def _extract_image_from_container(self, filepath: str) -> List[Dict[str, str]]:
        images = []
        try:
            stream, stat = self.container.get_archive(filepath)
            file_obj = io.BytesIO()
            for chunk in stream:
                file_obj.write(chunk)
            file_obj.seek(0)
            with tarfile.open(fileobj=file_obj, mode='r') as tar:
                member_name = os.path.basename(filepath)
                for m in tar.getmembers():
                    if m.name.endswith(member_name):
                        img_data = tar.extractfile(m).read()
                        b64_img = base64.b64encode(img_data).decode('utf-8')
                        images.append({"type": "image", "filename": member_name, "data": f"data:image/png;base64,{b64_img}"})
                        break
        except: pass
        return images

    def _wrap_code_with_plot_saving(self, code: str) -> str:
        if "matplotlib" in code or "plt." in code:
            header = "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
            footer = "\ntry:\n    if plt.get_fignums():\n        plt.savefig('/tmp/plot.png')\nexcept: pass"
            return header + code + footer
        return code

# 全局方法，供 nodes.py 调用
def run_python_code(code: str):
    sandbox = DockerSandbox()
    stdout, stderr, images = sandbox.run_code(code)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "images": images,
        "returncode": 0 if not stderr else 1
    }
