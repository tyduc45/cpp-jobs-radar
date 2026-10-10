# C++ Jobs Radar

每天收集全球多家公司的 C++ 相关岗位（包含实习），使用 GitHub Actions 定时运行、GitHub Pages 展示，新岗位通过 SMTP 邮件发送摘要和完整 CSV。

- **网站**：https://tyduc45.github.io/cpp-jobs-radar/
- **运行记录**：https://github.com/tyduc45/cpp-jobs-radar/actions
- **时间**：每天 **Australia/Sydney 00:00**，自动跟随夏令时。GitHub 队列可能延迟或丢弃计划任务，并非准点 SLA。
- **筛选**：关键词、国家/地区、城市、Remote / On-site / Hybrid、Full-time / Intern / Part-time / Contract、公司、C++ 匹配范围、首次发现时间。
- **身份限制过滤**：网页、邮件正文和 CSV 共用完整 JD 筛查，排除明确的公民、国籍、永久居民 / 绿卡、U.S. Person 和强制安全许可要求。平等就业声明里的国籍词汇不作为限制。尚未按当前规则检查过的旧数据和缺失 JD 的记录暂不展示或发送。

## 邮件设置

仓库 Settings → Secrets and variables → Actions 设置以下 secrets：

| Secret | 内容 |
|---|---|
| `MAIL_TO` | 收件邮箱（单个邮箱） |
| `SMTP_USER` | 发件邮箱 / SMTP 用户名 |
| `SMTP_PASSWORD` | SMTP 专用授权码，例如 Gmail 的 16 位应用专用密码。**不要使用邮箱登录密码**。 |
| `MAIL_FROM` | 可选，默认等于 SMTP_USER |

Repository variables：`SMTP_HOST`（默认 smtp.gmail.com），`SMTP_PORT`（默认 465 / SSL；其他端口使用 STARTTLS）。账号必须允许 SMTP 登录和发信。

Gmail 应用专用密码入口：https://myaccount.google.com/apppasswords ，需要先开启两步验证，部分受管理账号不支持。把密码直接填写到 GitHub Secret，避免发在聊天、提交到代码或放在命令参数中。配置后进入 Actions → Daily C++ jobs → Run workflow 即可验证。

未配置发信凭据时，网页仍部署，通知任务会明确报错，新岗位保留在队列。首次成功发信包含当前已发现的全部岗位；之后仅发送新增。没有新增时不发信。正文展示最多 60 条，**CSV 附件包含本次全部新增岗位**。

## 本地使用

Python 3.12+，只使用标准库，没有 pip 依赖。Python 必须安装有效的系统 CA 证书，不能关闭 TLS 验证。

```sh
python -m unittest discover -s tests -v
node --test tests/freshness.test.cjs
python radar.py crawl
python radar.py build
python -m http.server 8000 --directory site
```

前端时效测试使用 Node.js 内置测试工具；抓取与邮件运行不依赖 Node.js。访问 http://localhost:8000 。网页通过 `jobs.json` 加载数据，使用 HTTP 服务，不要直接双击 HTML 文件。`python radar.py notify` 使用环境变量中的 SMTP 配置发送邮件。

## 数据与可靠性

- `sources.json` 定义公司招聘源。支持 Greenhouse、Lever（含 EU）、Ashby 的公开招聘接口；Lever 完整分页；Ashby 排除未列出的岗位。没有地域限制，但**不代表覆盖全球所有公司或所有招聘网站**。
- 匹配标题或 JD 中的 C++、C++17/20、CPP、C plus plus 等，普通 C 和 C# 不匹配。网页区分“标题含 C++”和“JD 提及 C++”。来源摘要仅用于筛选，完整 JD 链接回发布方。
- 国家根据结构化地址、国家名称和已知城市保守识别，多个国家可同时命中。不根据公司总部或“EMEA/APAC”猜国家。无法识别的字段保留“未注明”；远程不代表允许任何国家申请。
- 岗位标题中的 Intern / Internship / Co-op / Working Student / 实习优先归类实习，即使源标注 FullTime。全职和办公方式只根据来源字段或明确的岗位描述识别，不根据城市猜 On-site。
- 通过去除跟踪参数后的 JD URL 去重，保留岗位识别参数；`data/state.json` 保留发现记录、关闭记录和通知状态，避免重跑或页面更新导致重复提醒。新 URL / 重新发布成新编号的岗位视为新岗位。
- **首次发现不等于发布日期**。源提供日期时单独展示。每次完整、成功抓取后，官方列表中已消失的岗位当次下架，记录关闭时间和原因。重新出现时自动恢复，保留首次发现和邮件回执，不重复提醒。
- **时效保护**：抓取失败、HTTP 错误和不完整分页不视为岗位关闭；距最后成功确认超过 `sources.json` 的 `max_unverified_hours`（默认 72 小时）则暂时隐藏，并停止邮件推送。恢复抓取后自动显示。停止跟踪的招聘源也不再展示。来源明确提供含时区的 `application_deadline` 时，过期即隐藏；不根据职位名称中的年份或含糊的正文日期猜测失效。
- 网页每分钟重新检查每个岗位的确认有效期，每 15 分钟重新获取已发布数据；即使定时抓取或部署停止，也不会无限展示过期快照。筛选结果、统计与邮件共用时效规则。每天抓取不能保证实时状态，发布方仍在列表中保留的过期岗位可能无法识别，最终以原始 JD 为准。
- 身份限制一经检出会立即从网页和通知队列排除；状态仍保留去重记录。`eligibility.py` 保存可测试的通用匹配规则和版本号，`data/state.json` 记录来源条款片段以便检查误判，不保存申请者的国籍或签证资料。
- 该过滤检查文字中的限制，**不等于已确认申请资格**：未提及限制、普通工作许可要求、签证担保、工时和课程条件仍需核对；目前主要覆盖英文和常见中、法、德文表述。即使身份条款列有另行申请出口许可的选项，也按严格排除策略隐藏。
- 请求超时 45 秒，对 429 / 5xx / 网络错误最多尝试 3 次，最多 4 个并行源。Greenhouse 校验总数与重复 ID，Lever 校验重复及重叠分页，拒绝用不完整结果批量下架。单源故障展示在网页，不阻塞其他来源；所有源都失败则 workflow 报错，旧记录受 72 小时时效保护。
- 队列先提交到 Git 再发邮件；SMTP 接受后写入回执。发送失败会重试。SMTP 接受但 Git 回执推送失败的极端情况下可能重复发送，无法保证跨 SMTP / Git 的严格 exactly-once；相同待发送集合使用稳定 Message-ID。
- 邮件账号、收件人和授权码仅存在 GitHub Secrets，不写入网页或数据文件。网页转义远程文本，禁用危险 URL，CSV 防公式注入。
- 每次运行提交抓取时间、状态和岗位变化。GitHub 对长期无仓库活动的公开仓库可能停用定时任务，需关注 Actions 运行状态。

## 扩充招聘源

在 `sources.json` 的 `sources` 数组追加：

```json
{"type":"greenhouse","board":"company-token","company":"Company"}
```

其他类型：`lever` / `ashby`。Lever EU 增加 `"region":"eu"`。board token 从该公司真实招聘页面获得；修改后手动运行并检查来源状态，不要把未验证的 token 当成可用来源。

修改定时时区时，同时调整 `.github/workflows/daily.yml` 的 `timezone` 和 `sources.json` 的 `timezone`；例如中国时间用 `Asia/Shanghai`。

## 官方接口参考

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [GitHub scheduled workflows 与时区](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
