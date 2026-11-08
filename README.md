# 门诊病历填写系统

从一段门诊问诊录音或对话文本，生成一份可存档的门诊病历 Markdown。

三个 AI 能力各司其职，按「字段值域的性质」分工，而不是按功能堆叠：

| 能力 | 用在哪 | 为什么 |
|---|---|---|
| ASR | 音频 → 带说话人的对话 | 声学问题，交给声学模型 |
| 决策模型 `typesafe/jev` | 说话人角色、症状域筛查、封闭字段 | 值域有限，返回概率；1~2 秒、几百 token，便宜且保留把握程度 |
| 大语言模型 `Qwen/Qwen3.8-27B` | 现病史、查体等开放字段 | 值域开放，枚举会丢信息 |

## 关键设计

**1. 字段按值域分类，不按科室分类**

- `ClosedField`：值是有限的（是否发热、紧急程度三档、要不要用药）→ jev
- `OpenField`：值是开放的自然语言（现病史、就诊科室、疼痛描述）→ LLM

医学描述大部分是开放的。「上腹偏右持续性钝痛向背部放射」装不进任何枚举。
所以不存在「消化科字段表」这种东西——患者发烧去消化科是正常的，
症状域可以同时命中多个，字段跟着症状走，科室是**输出**不是输入。

**2. 概率是信息，不压缩**

jev 每次返回完整概率分布。`has_fever` 的 `p=0.05` 和 `p=0.45` 含义完全不同，
所以封闭字段结果保留 `value / p / certainty / uncertain / ranked`，
把握不足的字段在病历里标「（把握 0.55）」，并进 warnings 提示人工复核。

**3. 提示词只在文件里**

`prompts/*.md`。不在代码里内嵌，改提示词不用改代码、不用发版。

提示词不写角色扮演。「你是一个医生」这类措辞既不必要也低效——
任务本身描述清楚就够了。结构化输出一律 JSON。

**4. 分层与依赖方向**

```
web / cli          接口层
  └ pipeline       只编排，不实现能力，不落盘
      ├ asr        音频 → Transcript（可插拔后端）
      ├ decision   封闭问题的概率判断
      ├ llm        提示词 → 文本
      ├ record     病历领域模型与 Markdown 渲染（纯函数）
      └ storage    写盘
  core             配置、凭据、传输、JSON 工具（不认识任何能力层）
```

各能力层通过 `core/contracts.py` 的 Protocol 注入，互相不 import。
换掉任何一个实现都不用改 pipeline。

## 目录

```
emr/
  app/
    core/        contracts / config / credentials / transport / jsons
    asr/         transcribers.py  speakers.py
    llm/         chat.py  prompts.py
    decision/    jev.py
    record/      form.py（字段定义）model.py  formfill.py  render.py
    pipeline/    record_pipeline.py
    storage/     writer.py
    web/         app.py  routes.py  pages.py
    compose.py   唯一的组装点
  prompts/       extract_open.md  complete.md
  tests/         pytest
  samples/       对话样例
  out/           生成的 md + json
```

新增症状域：往 `app/record/form.py` 的 `DOMAINS` 加一条。
新增封闭字段：加到对应域的 `closed_details` 或 `UNIVERSAL_CLOSED`。
这两件事都不需要改 pipeline。

## 配置

凭据独立管理，依次查找：

1. 环境变量 `EMR_API_KEY`
2. 项目根 `.env`（已在 `.gitignore`）
3. `~/.config/emr/credentials.json`（权限 600）

写第三条：

```python
from app.core.credentials import write_user_credentials
write_user_credentials("你的 key")
```

其余配置见 `.env.example`。默认：

- 大模型候选链 `Qwen/Qwen3.8-27B` → `Qwen3.8-Flash` → `deepseek-v4.1-flash` → `glm-5.3-flash`
  第一个不可用自动顺延
- 决策模型 `typesafe/jev` → `typesafe/jev-1.14.0`
- 时间预算 300 秒

## 运行

```bash
# 依赖在 emr/_vendor，run.py 会自动加进 sys.path
python3 run.py --host 0.0.0.0 --port 8085

# 或
PYTHONPATH=./_vendor:. python3 -m pytest tests -q
```

浏览器打开 `http://<host>:8085/`，三个入口：

- **直接录音**：浏览器内录，录完直接生成
- **上传音频**：wav / mp3 / m4a / webm
- **粘贴对话**：每行「角色：内容」

> **录音只在 https 或 localhost 下可用。** 这是浏览器的安全上下文限制，
> 不是本站的缺陷：裸 IP 走 http 时 `navigator.mediaDevices` 根本不存在，
> 自签证书也不行（浏览器不把自签 https 视为安全上下文）。
>
> 用裸 IP 访问时，页面会自动禁用录音按钮、切到「上传音频」页签，
> 并显示下面三条路径。要在浏览器里直接录，最省事的是 SSH 隧道：
>
> ```bash
> ssh -L 8084:127.0.0.1:8085 ubuntu@<服务器IP>
> # 然后打开 http://127.0.0.1:8084/
> ```

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 就绪状态、各模型候选链、提示词列表 |
| POST | `/api/record/text` | `{transcript, visited_at?, persist?}` |
| POST | `/api/record/audio` | multipart：`file`、`speakers`、`persist` |
| GET | `/api/records?limit=` | 历史产出列表 |
| GET | `/api/record/{stem}/markdown` | 取某份 Markdown |

响应里除了 `markdown`，还有 `transcript`、`record`、`closed`（含概率）、
`hit_domains`、`models_used`、`warnings`、`elapsed_s`、`files`。

## 已知限制

- **同一人配音的录音无法做声学分离**。此时 jev 会判不出医患双方，
  系统退回按对话里的「医生：」「患者：」标注切分，并给出 warning。
- **ASR 后端依赖百炼 CLI**（`bl speech recognize`，带说话人分离）。
  未安装时自动退回 mock 后端，只用于离线演示。
- 浏览器直接录音在无麦克风的机器上会报「Requested device not found」，
  这是浏览器行为，不是错误。
