# 招聘平台可见浏览器采集工具

运行：

```powershell
python main.py
```

程序会打开可见 Chrome 浏览器，逐页滚动、采集当前页并优先点击网页上的“下一页”。

Boss直聘登录流程：

1. 在项目根目录的 `.credentials.json` 配置账号和密码。
2. 开始采集后，程序会在打开的 Chrome 中自动填写并尝试登录。
3. 手动完成短信、滑块或验证码。
4. 回到程序点击“已完成”。

账号密码保存在项目根目录的 `.credentials.json`（已加入 `.gitignore`，不会提交到 git）。
复制 `credentials.example.json` 为 `.credentials.json` 后填入各平台账号即可；需要登录时程序会自动读取并尝试填写、点击登录。短信、滑块或验证码仍需在浏览器中手动完成。

登录会话保存在项目的 `.browser_profile` 目录中，以便下次复用。删除该目录即可清除浏览器会话。
