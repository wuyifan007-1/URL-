import tkinter as tk
from tkinter import filedialog, messagebox
import asyncio
import aiohttp
import threading
from queue import Queue


class URLScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("URL百万级存活扫描器")
        self.root.geometry("800x800")

        # 文件路径
        self.file_path = tk.StringVar()

        # 参数设置
        self.concurrent_requests = tk.IntVar(value=100)
        self.timeout = tk.IntVar(value=5)
        self.proxy = tk.StringVar(value="http://127.0.0.1:10808")  # 默认代理地址

        # 成功和失败 URL 列表
        self.success_urls = []
        self.failed_urls = []

        # 控制停止扫描的变量
        self.stop_scan = False

        # 日志队列，用于线程安全更新日志和结果
        self.log_queue = Queue()

        # 创建 GUI 界面
        self.create_widgets()

    def create_widgets(self):
        # 文件选择部分
        tk.Label(self.root, text="选择包含 URL 的文件:").pack(pady=5)
        tk.Entry(self.root, textvariable=self.file_path, width=70).pack(pady=5)
        tk.Button(self.root, text="浏览", command=self.browse_file).pack(pady=5)

        # 参数设置部分
        tk.Label(self.root, text="并发数:").pack(pady=5)
        tk.Entry(self.root, textvariable=self.concurrent_requests, width=10).pack(pady=5)

        tk.Label(self.root, text="超时时间 (秒):").pack(pady=5)
        tk.Entry(self.root, textvariable=self.timeout, width=10).pack(pady=5)

        # 代理设置部分
        self.use_proxy = tk.BooleanVar(value=False)  # 默认不开启代理
        tk.Checkbutton(self.root, text="启用代理", variable=self.use_proxy).pack(pady=5)

        tk.Label(self.root, text="代理地址:").pack(pady=5)
        tk.Entry(self.root, textvariable=self.proxy, width=40).pack(pady=5)

        # 扫描按钮
        tk.Button(self.root, text="开始扫描", command=self.start_scan).pack(pady=10)

        # 停止扫描按钮
        tk.Button(self.root, text="停止扫描", command=self.stop_scanning).pack(pady=5)

        # 日志显示
        tk.Label(self.root, text="扫描日志:").pack(pady=5)
        self.log_text = tk.Text(self.root, height=10, width=95, state="normal")
        self.log_text.pack(pady=5)

        # 扫描结果显示
        tk.Label(self.root, text="扫描结果:").pack(pady=5)
        self.result_text = tk.Text(self.root, height=10, width=95, state="normal")
        self.result_text.pack(pady=5)

    def browse_file(self):
        """选择文件"""
        file = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if file:
            self.file_path.set(file)

    def log_message(self, message, result=False):
        """记录消息到日志队列"""
        self.log_queue.put((message, result))

    def update_ui(self):
        """更新日志和结果到界面"""
        while not self.log_queue.empty():
            message, result = self.log_queue.get()
            if result:
                self.result_text.insert(tk.END, f"{message}\n")
                self.result_text.see(tk.END)
            else:
                self.log_text.insert(tk.END, f"{message}\n")
                self.log_text.see(tk.END)
        self.root.after(100, self.update_ui)

    def start_scan(self):
        """开始扫描"""
        file_path = self.file_path.get()
        if not file_path:
            messagebox.showerror("错误", "请选择 URL 文件")
            return

        concurrent_requests = self.concurrent_requests.get()
        timeout = self.timeout.get()

        if concurrent_requests <= 0 or timeout <= 0:
            messagebox.showerror("错误", "请设置有效的并发数和超时时间")
            return

        # 清空之前的结果
        self.success_urls = []
        self.failed_urls = []

        # 设置停止扫描标志为 False
        self.stop_scan = False

        # 启动扫描线程
        threading.Thread(
            target=self.run_scan, args=(file_path, concurrent_requests, timeout)
        ).start()

        # 启动 UI 更新
        self.update_ui()

    def stop_scanning(self):
        """停止扫描"""
        self.stop_scan = True
        self.log_message("扫描已停止")

    def run_scan(self, file_path, concurrent_requests, timeout):
        """运行扫描任务"""
        try:
            with open(file_path, "r") as f:
                urls = [line.strip() for line in f if line.strip()]
        except Exception as e:
            self.log_message(f"加载文件出错: {e}")
            return

        self.log_message(f"加载了 {len(urls)} 个 URL，开始扫描...")

        # 在主线程中运行 asyncio 事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.scan_urls(urls, concurrent_requests, timeout))

        self.log_message("扫描完成！")

        # 保存结果到文件
        self.save_results()

    async def fetch_url(self, session, url, timeout, proxy):
        """异步获取 URL 状态"""
        try:
            # 如果启用代理
            proxy_url = f"http://{proxy}" if proxy else None
            async with session.get(url, timeout=timeout, proxy=proxy_url) as response:
                if response.status == 200:
                    self.success_urls.append(url)
                    self.log_message(f"{url} - 成功", True)
                else:
                    self.failed_urls.append(url)
                    self.log_message(f"{url} - 失败", True)
        except:
            self.failed_urls.append(url)
            self.log_message(f"{url} - 失败", True)

    async def scan_urls(self, urls, concurrent_requests, timeout):
        """扫描所有 URL"""
        semaphore = asyncio.Semaphore(concurrent_requests)
        async with aiohttp.ClientSession() as session:
            tasks = [
                asyncio.create_task(self.safe_fetch_url(session, url, semaphore, timeout))
                for url in urls
            ]
            await asyncio.gather(*tasks)

    async def safe_fetch_url(self, session, url, semaphore, timeout):
        """带限流的 URL 检查"""
        async with semaphore:
            if self.stop_scan:
                return  # 停止扫描
            await self.fetch_url(session, url, timeout, self.proxy.get() if self.use_proxy.get() else None)

    def save_results(self):
        """保存扫描结果到文件"""
        try:
            with open("success_urls.txt", "w") as f:
                f.writelines(f"{url}\n" for url in self.success_urls)

            with open("failed_urls.txt", "w") as f:
                f.writelines(f"{url}\n" for url in self.failed_urls)

            self.log_message(f"成功 URL 保存到: success_urls.txt")
            self.log_message(f"失败 URL 保存到: failed_urls.txt")
        except Exception as e:
            self.log_message(f"保存结果出错: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = URLScannerApp(root)
    root.mainloop()
