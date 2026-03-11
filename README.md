# 杀戮尖塔 2 存档修改器

《杀戮尖塔 2》本地存档修改器与结构化查看工具。

面向 **Slay the Spire 2** 提供：

- 图形界面编辑
- 结构化字段编辑
- 原始 JSON 直接查看与修改
- `current_run` 文件探测与辅助验证
- 从 `SlayTheSpire2.pck` 提取本地化文本索引，用于中文名预览与搜索

<img width="1086" height="713" alt="image" src="https://github.com/user-attachments/assets/dd272b04-68cd-4555-af96-9df41de39757" />

## 安装


克隆并安装依赖：

```powershell
git clone https://github.com/RusianHu/slaythespire-editor.git
cd .\slaythespire-editor
python -m pip install -U -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

---

## 启动方式

### 启动图形界面

```powershell
python .\editor_sts2.py
```

### 按需指定存档目录 / PCK 启动

```powershell
python .\editor_sts2.py --save-dir "C:\Program Files (x86)\Steam\userdata\<SteamID>\2868840\remote\profile1\saves"
python .\editor_sts2.py --pck-path "D:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck"
```

若不传参数，程序会优先尝试"已保存配置 -> 自动探测"。

---

## CLI 用法

`--save-dir` / `--pck-path` 为可选覆盖参数，未传时同样会尝试已保存配置和自动探测。

### 1. 预览可识别存档

```powershell
python .\editor_sts2.py --cli-preview
```

### 2. 预览 PCK 本地化内容

```powershell
python .\editor_sts2.py --cli-localization-preview
```

### 3. 探测当前战局文件

```powershell
python .\editor_sts2.py --cli-current-run-probe
```

### 4. 对 current_run 做 dry-run 测试

```powershell
python .\editor_sts2.py --cli-current-run-apply --dry-run --gold 999 --append-potion-id POTION.ENERGY_POTION
```

### 5. watch 模式观察变化

```powershell
python .\editor_sts2.py --cli-current-run-watch --watch-seconds 60 --interval-seconds 1
```

---

## 项目定位

本工具主要用于编辑和查看《杀戮尖塔 2》的本地存档数据，重点覆盖以下文件：

- `prefs.save`
- `progress.save`
- `history/*.run`
- `current_run.save`
- `current_run.save.backup`

项目当前以 **UTF-8 JSON 读写** 为核心， 1 代则是 `.autosave` 的加解密路线。


## 当前能力

### 1. 图形界面

启动后可在桌面 GUI 中：

- 浏览可识别的 2 代存档文件
- 查看结构化摘要
- 编辑基础字段
- 编辑卡组 / 遗物 / 药水列表
- 直接切换到 JSON 页签手工修改原始内容
- 保存时自动创建备份

**路径管理能力：**

- 可通过"路径"菜单或"路径设置"统一管理存档目录与 PCK
- 支持手动选择存档目录 / PCK
- 支持自动探测 Steam 存档目录与游戏 PCK
- 路径会保存到本地配置，后续启动自动回用
- PCK 切换后中文名预览与候选搜索会自动刷新

### 2. 结构化编辑

当前已支持的主要方向包括：

- run 基础字段
  - `ascension`
  - `seed`
  - `game_mode`
  - `win`
- 玩家字段
  - `character`
  - `max_potion_slot_count`
- 玩家列表字段
  - `deck`
  - `relics`
  - `potions`
- `progress.save` 基础字段
- `prefs.save` 基础字段

### 3. 本地化探测

可从 `SlayTheSpire2.pck` 中提取本地化 JSON，构建以下索引：

- cards
- relics
- potions
- characters

这些索引可用于：

- 中文名显示
- 候选搜索
- 内部 ID / 英文名 / 中文名混合匹配

**未设置 PCK 时的行为：**

- 未设置 PCK 时，仍可编辑 JSON
- 但中文名显示、候选搜索会退化为仅内部 ID 或部分缺失的模式

### 4. CLI 辅助能力

除 GUI 外，还提供命令行模式，用于：

- 存档预览
- 本地化预览
- `current_run` 探测
- `current_run` dry-run 试补丁
- watch 观察

---

## 运行环境

- Windows 11
- Python 3
- `wxPython`
- 其他依赖见 `requirements.txt`

---



## 路径策略与配置

### 自动探测顺序

- **存档目录**：自动枚举 Steam `userdata/<SteamID>/2868840/remote/profile*/saves`
- **PCK**：自动枚举 Steam 库中的 `Slay the Spire 2/SlayTheSpire2.pck`

### 手动回退

- **GUI**：可通过"路径"菜单和"路径设置"手动选择
- **CLI**：可通过 `--save-dir` / `--pck-path` 显式指定

### 配置保存

- 已选择的存档目录与 PCK 会保存到本地配置文件
- 后续启动时优先使用已保存配置
- 配置文件位于：
  ```text
  %APPDATA%\slaythespire-editor\sts2_paths.json
  ```

### 当前战局 backup 补充发现

- 仍会额外尝试从：
  ```text
  %APPDATA%\SlayTheSpire2\steam\...
  ```
  递归补充发现 `current_run.save.backup`

---

## 写回与备份策略

保存 2 代 JSON 文件时，工具会：

1. 先识别文件类型
2. 写回前创建时间戳备份
3. 以 UTF-8 编码写入
4. 使用格式化 JSON 输出，便于人工检查

备份文件示例：

```text
current_run.save.20250308_153000.bak
```

---

## 使用注意事项

### 1. 显示名不等于存档值

GUI 中看到的中文名、英文名、候选标签，本质上只是展示层。

**真正写回存档的必须是内部 ID。**

### 2. 修改存档不代表补发即时效果

直接改存档后，游戏未必会自动补发某些"获得时立即触发"的效果。

### 3. `current_run` 生命周期需谨慎判断

- `current_run.save` 存在，不一定代表游戏当前正在运行
- `current_run.save.backup` 可能只是残留文件
- live 文件与 backup 文件需要区分对待

### 4. 路径未命中时的表现

- **存档目录无效时**：会阻止读取并给出错误提示
- **PCK 缺失时**：不会阻止 JSON 编辑，但会影响中文名与候选搜索体验

---

## 已知边界

当前版本仍属于第一版结构化编辑器，主要限制包括：

- 并未覆盖全部复杂 schema
- 地图 / 路线目前以摘要展示为主
- 不保证游戏会在所有场景下热重载被修改的文件
- 某些运行期行为仍需要进一步观察验证

---

## 许可证

本项目采用 [GNU General Public License v3.0](./LICENSE) 许可证，详见仓库根目录下的 [LICENSE](./LICENSE)。
