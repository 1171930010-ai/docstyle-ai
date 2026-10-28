# 协作开发

请先在本机运行并验证修改。建议为每项工作建立分支，提交 Pull Request，说明目的、修改范围、验证结果和已知限制，至少由另一位协作者复核后合并。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -q
.venv/bin/python server.py --port 8770 --open
```

Windows 使用 `.venv\Scripts\python.exe`。绝不提交 API Key、真实稿件、用户项目包或本机数据。测试使用自建和获明确授权的样本；公式、文档保真与 Word/WPS 兼容性应区分自动测试和实际软件验证。不要将网页上传到公开服务来代替本地处理，除非明确设计并验证认证、数据隔离和安全边界。

已有 `vendor/` 为项目运行所需第三方资源；请保留其许可及版权声明。此仓库未声明项目本身的开源许可证，是否开源及许可证由项目所有者决定。
