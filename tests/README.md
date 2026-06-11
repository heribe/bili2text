# LongCat API 测试工具

这个测试工具用于验证 LongCat 大模型的 API 通讯是否正常，并支持流式接收测试。

## 如何使用

在项目根目录下（即 `E:\Code\bili2text` 或 NAS 里的项目根目录），通过终端运行以下命令：

### 1. 基础连通性测试（短连接测试）
发一句 "Test the connection." 给大模型，验证 API Key 和网络是否连通，同时测试流式响应：
```bash
uv run python tests/test_longcat_api.py short
```
*(或者不加参数直接运行默认也是短连接测试)*

### 2. 真实负载测试（长文本大批次测试）
从 `tests/test.txt` 中读取前 50 句话，完全模拟真实后端的请求体和提示词发给大模型。
这个指令用来测试：在单次发给大模型几十句话时，大模型处理和流式返回的时间是多长，是否存在被服务器掐断（504）的问题。
```bash
uv run python tests/test_longcat_api.py long
```
