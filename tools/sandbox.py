import docker
import time
import logging
import tarfile
import io
import base64
import os
import uuid
from typing import Tuple, List, Optional, Dict

logger = logging.getLogger("Tools-Sandbox")

class DockerSandbox:
    def __init__(self, image: str = "python:3.9-slim"):
        # [Optimization] 优雅降级：检查 Docker 是否可用
        self.docker_available = False
        try:
            self.client = docker.from_env()
            self.client.ping()
            self.docker_available = True
        except Exception as e:
            logger.warning(f"⚠️ Docker not available: {e}. Entering Mock Mode.")
            self.client = None

        self.image = image
        # [Critical Fix] 并发灾难修复：使用动态生成的 UUID 作为容器名
        # 防止多个任务同时运行时抢占同一个容器
        self.container_name = f"swarm_sandbox_{uuid.uuid4().hex[:8]}"
        self.container = None

    def run_code(self, code: str, timeout: int = 30) -> Tuple[str, str, List[Dict[str, str]]]:
        # [Optimization] Mock Mode
        if not self.docker_available:
            return (
                "[Mock Mode] Docker is not running. Code cannot be executed safely.\n(This is a simulated output defined in sandbox.py)", 
                "", 
                []
            )

        try:
            # 启动容器
            # [Optimization] 增加 auto_remove=False 以便我们在提取文件后再手动删除
            # 使用 network_mode='none' 隔离网络
            self.container = self.client.containers.run(
                self.image,
                detach=True,
                tty=True,
                name=self.container_name,
                mem_limit="512m",
                network_mode="none" 
            )
            
            run_id = str(uuid.uuid4())[:8]
            script_filename = f"script_{run_id}.py"
            plot_filename = f"plot_{run_id}.png"
            container_plot_path = f"/tmp/{plot_filename}"

            wrapped_code = self._wrap_code_with_plot_saving(code, container_plot_path)
            self._write_file_to_container("/tmp", script_filename, wrapped_code)
            
            # [Optimization] 增加超时控制 (使用 timeout 命令)
            cmd = f"timeout {timeout}s python -u /tmp/{script_filename}"
            exec_result = self.container.exec_run(cmd)
            
            stdout = exec_result.output.decode("utf-8", errors="replace")
            stderr = ""
            
            # 检查超时状态码 (124 是 timeout 命令的标准退出码)
            if exec_result.exit_code == 124:
                stderr = f"❌ Execution Timed Out (Limit: {timeout}s)"
            elif exec_result.exit_code != 0:
                stderr = stdout # 通常 stderr 也会合并在 output 中
            
            # 提取图片
            images = self._extract_image_from_container(container_plot_path)
            
            return stdout, stderr, images
            
        except Exception as e:
            return "", f"System Error: {str(e)}", []
        finally:
            # [Optimization] 确保容器被清理，防止资源泄漏
            if self.container:
                try:
                    self.container.remove(force=True)
                except:
                    pass

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
            # 使用 get_archive 获取文件流
            stream, stat = self.container.get_archive(filepath)
            file_obj = io.BytesIO()
            for chunk in stream:
                file_obj.write(chunk)
            file_obj.seek(0)
            with tarfile.open(fileobj=file_obj, mode='r') as tar:
                # 获取 tar 包中的文件名（可能不带路径）
                for m in tar.getmembers():
                    if m.isfile(): # 只要是文件就提取
                        img_data = tar.extractfile(m).read()
                        b64_img = base64.b64encode(img_data).decode('utf-8')
                        images.append({"type": "image", "filename": m.name, "data": f"data:image/png;base64,{b64_img}"})
        except Exception as e:
            # [Fix] 吞没异常会导致图片丢失且无法排查，至少记录日志
            logger.error(f"Image extraction failed: {e}")
            pass
        return images

    def _wrap_code_with_plot_saving(self, code: str, save_path: str) -> str:
        # [Fix] 只有在确实导入了 matplotlib 时才注入代码
        # 简单的字符串检查可能误判，这里稍微严格一点，但仍然保持简单
        if "import matplotlib" in code or "from matplotlib" in code:
            header = f"import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
            footer = f"\ntry:\n    if plt.get_fignums():\n        plt.savefig('{save_path}')\nexcept: pass"
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
