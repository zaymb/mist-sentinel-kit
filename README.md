# sentinel — 一只自己养的仓库哨兵

盯住一个 GitHub 仓库的 issue 和 PR，从开单到关单的每一次动静都给你一行提醒。
一个 Python 单文件，只用标准库，外部依赖只有一个已经登录的 `gh` CLI。

跑一轮就退出，不常驻、不守进程。什么时候跑由你的 cron 或 launchd 说了算。

## 为什么不带 bot

因为通知这件事不该跨过别人的服务器。

这里没有 token，没有内置的 Telegram / Slack / Discord 出口，也不替你连任何第三方。
事件出来之后往哪儿走，由你 config 里的 `notify_cmd` 一行决定——`ntfy`、
`terminal-notifier`、`osascript`、你自己那个只有你能用的推送脚本，都行。
哨兵只负责把变化看清楚，投递口是你自己的。

## 装三步

**一、拿到脚本。** clone 或者直接把这个目录拷到本地，位置随你，下文一律写作
`~/sentinel-kit`。需要一个 3.9 以上的 Python（macOS 自带的就够）和一个登录过的 `gh`：

```sh
gh auth status          # 看到 ✓ Logged in 才往下走
python3 --version
```

**二、配 config。**

```sh
cd ~/sentinel-kit
cp config.example.json config.json
```

然后改 `config.json`：`repo` 换成你要盯的仓库，`subscriptions` 按下一节写，
`notify_cmd` 换成你自己的投递命令（留空就打印到 stdout）。`{line}` 会被替换成
事件行，替换时自动做 shell 转义，不用自己加引号。

先手跑一次，第一轮只建基线、不投递，是正常的：

```sh
python3 sentinel.py            # 第一次：安静，只写 state/
python3 sentinel.py --dry-run  # 想看事件行原样，不走 notify_cmd
```

**三、挂上调度。** 二选一。

cron（macOS / Linux 通用），`crontab -e` 加一行，每 5 分钟一轮：

```
*/5 * * * * cd ~/sentinel-kit && /usr/bin/python3 sentinel.py >> ~/sentinel-kit/sentinel.log 2>&1
```

launchd（仅 macOS），存成 `~/Library/LaunchAgents/local.sentinel.plist`，
把 `USERNAME` 换成你自己的家目录名：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.sentinel</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/USERNAME/sentinel-kit/sentinel.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/USERNAME/sentinel-kit</string>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardErrorPath</key><string>/Users/USERNAME/sentinel-kit/sentinel.log</string>
</dict>
</plist>
```

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.sentinel.plist
```

launchd 和 cron 都不会自动带上 Homebrew 的 PATH，`gh` 装在 `/opt/homebrew/bin`
或 `/usr/local/bin` 的话，cron 那行请把 `gh` 所在目录写进 crontab 顶部的 `PATH=`，
launchd 用上面的 `EnvironmentVariables`。

## 订阅表怎么写

`subscriptions` 是一个数组，从上往下看，命中任意一条就投递。
`match` 三种写法：标题子串（不分大小写）、`#编号`、`*` 全场。
`events` 是事件名数组，或者 `*` 表示这条订阅的全部事件。

只订自己认领的那个包，别人的动静不吵我：

```json
"subscriptions": [
  { "match": "P4", "events": "*" }
]
```

不看细节，只要全场大事——新单、新 PR、合并、关闭：

```json
"subscriptions": [
  { "match": "*", "events": ["new_issue", "new_pr", "pr_merged", "pr_closed"] }
]
```

全订，一条不漏：

```json
"subscriptions": [
  { "match": "*", "events": "*" }
]
```

也可以叠着写，比如「我的包全订 + 全场只看合并 + 盯住某一号单子」：

```json
"subscriptions": [
  { "match": "P4",  "events": "*" },
  { "match": "#16", "events": "*" },
  { "match": "*",   "events": ["pr_merged"] }
]
```

### 别被刷屏：digest

`digest.instant_events` 里的事件立刻投递，其余的攒进 `state/pending-batch.json`，
每 `batch_window_runs` 次运行冲一次批。默认是大事即时、评论和改动攒五轮再一起给你。
想全部即时，把 `instant_events` 写成 `"*"`。

## 事件谱

| 事件 | 什么时候出 |
| --- | --- |
| `new_issue` | 新开了一个 issue |
| `issue_comment` | issue 新增评论，带 `+N (共C)` |
| `issue_closed` | issue 关闭 |
| `new_pr` | 新开了一个 PR |
| `pr_head` | PR 有新 commit（head 变了） |
| `pr_review` | 审查结论翻转，如 `APPROVED` / `CHANGES_REQUESTED` / `CLEARED` |
| `pr_comment` | PR 新增评论 |
| `pr_merged` | PR 合并 |
| `pr_closed` | PR 关闭未合并 |

事件行长这样：

```
17:01 [P4] issue_comment +2 (共16) 认领件 P4：会话生杀 + 判卷驱动装配——killSession 与 cre… (#16)
```

方括号里是路由标签：标题里带 `P1`–`P9` 包号就用包号（末尾补 `(#单号)`），
没有就直接是 `#单号`。标题截断到 40 字。

## 状态与出事的时候

- `state/issues.json`、`state/prs.json` — 上一轮的快照。删掉就重新建基线（会安静一轮）。
- `state/pending-batch.json` — 攒着还没冲的批。
- `state/errors.log` — `gh` 调用失败只写一行就退出，不重试、不轰炸。
  没收到提醒又觉得不对，第一个看这里。
- 首轮不投递是刻意的，否则你会被整个仓库的历史砸一脸。
- 编号和评论数来自 `gh` 的列表接口；`issue_limit` / `pr_limit` 控制每轮取多少条，
  仓库很大就调高。

## 卸载

```sh
launchctl bootout gui/$(id -u)/local.sentinel 2>/dev/null; crontab -l | grep -v sentinel.py | crontab -; rm -rf ~/sentinel-kit
```

MIT。拿去改，不用回来问。

> 备注：包号标签由标题正则识别（P1–P99），非写死清单；无包号的条目用 `#编号` 作标签。新主线无需改代码，订阅表加行即可。
