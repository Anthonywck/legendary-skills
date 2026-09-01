# 恶意代码特征库

## 数据来源
CWE通用弱点枚举、MITRE ATT&CK框架、CNVD国家信息安全漏洞共享平台、微步在线威胁情报、360威胁情报中心、奇安信威胁情报中心、安全牛社区

## 致命风险特征

### 破坏性系统命令

| 特征代码 | 风险说明 | CWE | ATT&CK |
|---------|---------|-----|--------|
| rm -rf / | 无保护递归删除，可清空整个文件系统 | CWE-775 | T1485 |
| rm -rf ~ | 删除用户主目录全部数据 | CWE-775 | T1485 |
| mkfs.* | 格式化磁盘分区 | CWE-775 | T1561 |
| dd if=/dev/zero of= | 用零覆写磁盘/分区 | CWE-775 | T1561 |
| shred -f / | 安全删除/覆写文件 | CWE-775 | T1485 |
| :(){ :\|:& };: | Fork炸弹，耗尽系统资源 | CWE-400 | T1499.001 |
| chmod -R 777 / | 全系统权限开放 | CWE-732 | T1548 |

### 动态代码执行

| 特征代码 | 语言 | 风险说明 | CWE |
|---------|------|---------|-----|
| eval(user_input) | Python/JS | 用户输入直接执行，命令注入 | CWE-94 |
| exec(code_string) | Python | 字符串作为代码执行 | CWE-94 |
| subprocess.call(cmd, shell=True) | Python | Shell注入 | CWE-78 |
| os.system(cmd) | Python | 系统命令直接执行 | CWE-78 |
| child_process.exec(cmd) | Node.js | 子进程命令执行 | CWE-78 |
| Function(code_string)() | JS | 动态函数构造 | CWE-94 |

### 硬编码凭证

| 特征模式 | 风险说明 | CWE |
|---------|---------|-----|
| AKIA[0-9A-Z]{16} | AWS Access Key | CWE-798 |
| [A-Za-z0-9/+=]{40} (with aws context) | AWS Secret Key | CWE-798 |
| -----BEGIN (RSA\|EC\|DSA) PRIVATE KEY----- | 私钥硬编码 | CWE-798 |
| (ghp\|gho\|github_pat_)_[A-Za-z0-9_]{36,} | GitHub Token | CWE-798 |
| sk-[A-Za-z0-9]{32,} | OpenAI/Anthropic API Key | CWE-798 |
| -----BEGIN PGP PRIVATE KEY----- | PGP私钥 | CWE-798 |

### 恶意混淆代码

| 特征模式 | 风险说明 | CWE |
|---------|---------|-----|
| base64.b64decode("...").decode() | Base64编码隐藏执行逻辑 | CWE-456 |
| bytes.fromhex("...").decode() | 十六进制编码隐藏 | CWE-456 |
| __import__(obfuscated_name) | 动态导入混淆模块 | CWE-94 |
| 变量名全为_、O0O0、l1l1等 | 代码混淆，隐藏意图 | CWE-456 |
| exec(compile(base64...)) | 多层编码嵌套 | CWE-94 |
| zlib.decompress(base64...) | 压缩+编码双层隐藏 | CWE-456 |

## 高危风险特征

### 系统提权

| 特征代码 | 风险说明 | CWE | ATT&CK |
|---------|---------|-----|--------|
| sudo (without specific command) | 无限制sudo提权 | CWE-250 | T1548 |
| chmod 777 (on system dirs) | 关键目录全域开放 | CWE-732 | T1548 |
| setuid(0) | 设置root权限 | CWE-250 | T1548 |
| chown root | 修改文件所有者为root | CWE-250 | T1548 |

### 远程后门

| 特征代码 | 风险说明 | CWE | ATT&CK |
|---------|---------|-----|--------|
| socket.bind(("0.0.0.0", port)) | 监听所有网络接口 | CWE-200 | T1571 |
| socket.connect((unknown_ip, port)) | 连接未知远程服务器 | CWE-200 | T1071 |
| reverse_shell / pentestmonkey | 反向Shell | CWE-94 | T1059 |
| subprocess.Popen(reverse_shell_cmd) | 执行反向Shell命令 | CWE-78 | T1059 |
| nc -e /bin/bash | Netcat反向Shell | CWE-78 | T1059 |
| /dev/tcp/ | Bash反向Shell | CWE-78 | T1059 |

### 挖矿代码

| 特征模式 | 风险说明 | 检测依据 |
|---------|---------|---------|
| stratum+tcp:// | 矿池协议连接 | 微步威胁情报 |
| pool.minexmr.com / pool.supportxmr.com | 已知门罗币矿池域名 | 360威胁情报 |
| xmrig / minerd / cpuminer | 已知挖矿程序名 | CNVD通告 |
| --donate-level / --pool-passwd | 挖矿程序特有参数 | 奇安信情报 |
| crontab -e + */5 * * * * | 5分钟定时任务驻留 | ATT&CK T1053 |
| nohup ... & disown | 后台静默运行 | ATT&CK T1569 |
| pkill -f xmrig; sleep; restart | 挖矿进程守护/自重启 | 微步情报 |

### 数据窃取

| 特征代码 | 风险说明 | CWE | ATT&CK |
|---------|---------|-----|--------|
| open(os.path.expanduser("~/.ssh/")) | 读取SSH密钥 | CWE-200 | T1552 |
| open(os.path.expanduser("~/.aws/credentials")) | 读取AWS凭证 | CWE-798 | T1552 |
| sqlite3.connect(browser_cookie_path) | 读取浏览器Cookie | CWE-200 | T1539 |
| keylogger / pynput.keyboard.Listener | 键盘记录 | CWE-200 | T1056 |
| clipboard.paste() | 剪贴板窃取 | CWE-200 | T1115 |
| shutil.copy2(sensitive_file, upload_dir) | 复制敏感文件到上传目录 | CWE-200 | T1560 |

## 中危风险特征

### 不安全网络请求

| 特征代码 | 风险说明 | CWE |
|---------|---------|-----|
| requests.get("http://...") | 明文HTTP请求 | CWE-319 |
| urllib.request.urlopen("http://...") | 明文HTTP请求 | CWE-319 |
| verify=False | 禁用SSL证书验证 | CWE-295 |
| curl -k / curl --insecure | 禁用SSL验证 | CWE-295 |
| requests.post(url, data=..., verify=False) | 禁用验证的POST请求 | CWE-295 |

### 越权文件操作

| 特征代码 | 风险说明 | CWE |
|---------|---------|-----|
| open("/etc/shadow") | 读取系统密码文件 | CWE-200 |
| open("/etc/passwd", "w") | 写入系统用户文件 | CWE-73 |
| os.walk("/") | 遍历整个文件系统 | CWE-200 |
| glob.glob("/home/**/*") | 扫描所有用户目录 | CWE-200 |

### 外部脚本加载

| 特征代码 | 风险说明 | CWE |
|---------|---------|-----|
| curl ... \| bash / wget ... \| sh | 无校验执行远程脚本 | CWE-829 |
| pip install unknown_package | 安装未知来源包 | CWE-829 |
| npm install unknown_package | 安装未知来源包 | CWE-829 |
| import from unknown_url | 从未知URL导入 | CWE-829 |

## 低危风险特征

| 特征代码 | 风险说明 | CWE |
|---------|---------|-----|
| traceback.print_exc() | 完整错误堆栈泄露 | CWE-209 |
| print(os.path.abspath(__file__)) | 本地路径明文暴露 | CWE-200 |
| logging.debug(detailed_sensitive_info) | 敏感信息日志记录 | CWE-532 |
| TODO/FIXME含密码 | 注释中遗留敏感信息 | CWE-798 |

## TRAE专属检测

| 检测项 | 风险说明 |
|--------|---------|
| SKILL.md文件名为小写skill.md | TRAE平台要求大写，可能导致加载异常 |
| SKILL.md缺少YAML front matter | 必需字段name/description缺失 |
| SKILL.md的allowed-tools含高危工具 | 如Bash、Shell等直接命令执行工具 |
| SKILL.md引用外部脚本但无校验 | references/中引用的脚本无完整性校验 |
| 参赛违规内容 | 违规引导、虚假宣传、诱导消费等 |
