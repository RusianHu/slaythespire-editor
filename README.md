# 杀戮尖塔 2 存档修改器

《杀戮尖塔 2》本地存档修改器与结构化查看工具。

本项目面向 **Slay the Spire 2** 的 JSON 存档编辑场景，提供：

- 图形界面编辑
- 结构化字段编辑
- 原始 JSON 直接查看与修改
- `current_run` 文件探测与辅助验证
- 从 `SlayTheSpire2.pck` 提取本地化文本索引，用于中文名预览与搜索



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

安装依赖示例：

```powershell
python -m pip install -U -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

---

## 启动方式

### 启动图形界面

```powershell
python .\editor_sts2.py
```

### 指定存档目录启动

```powershell
python .\editor_sts2.py --save-dir "C:\Program Files (x86)\Steam\userdata\323507751\2868840\remote\profile1\saves"
```

---

## CLI 用法

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

## 默认路径参考

### 游戏目录

```text
D:\SteamLibrary\steamapps\common\Slay the Spire 2
```

### Steam 远程存档目录

```text
C:\Program Files (x86)\Steam\userdata\323507751\2868840\remote\profile1\saves
```

### 本地运行期备份候选根目录

```text
%APPDATA%\SlayTheSpire2\steam\...
```

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

直接改存档后，游戏未必会自动补发某些“获得时立即触发”的效果。

### 3. `current_run` 生命周期需谨慎判断

- `current_run.save` 存在，不一定代表游戏当前正在运行
- `current_run.save.backup` 可能只是残留文件
- live 文件与 backup 文件需要区分对待

---

## 已知边界

当前版本仍属于第一版结构化编辑器，主要限制包括：

- 并未覆盖全部复杂 schema
- 地图 / 路线目前以摘要展示为主
- 不保证游戏会在所有场景下热重载被修改的文件
- 某些运行期行为仍需要进一步观察验证

---

## 许可证

[文件](./LICENSE)
