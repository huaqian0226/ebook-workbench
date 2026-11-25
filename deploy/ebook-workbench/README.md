# 电子书工作台

本目录可直接部署 BookOrbit v3.10.0，使用发布镜像、PostgreSQL 和四个公开文件来源。应用、数据库镜像均由摘要固定。PDF、EPUB、CBZ 和有声书共用一个书库。桌面壳只需登记本机网址。[BookOrbit 安装](https://bookorbit.app/installation/) · [请求与选版](https://bookorbit.app/book-requests/)

## 安装

需要 Docker Compose、Python 3.12 或更新版本，以及一个只供本地用户访问的目录。在本目录执行以下命令。示例使用 Mac 应用支持目录与回环端口 8820。

```sh
instance="$HOME/Library/Application Support/BookOrbit"
python3 init_instance.py "$instance"
docker compose --project-directory "$instance" up -d --wait
python3 configure.py "$instance"
```

打开 [BookOrbit](http://127.0.0.1:8820/)，使用实例目录中 `owner.json` 的本地账户。初始化会为数据库、引导登录和来源凭据分别生成随机密钥。`configure.py` 会建立共享书架、设定请求默认目的地、载入公开来源并扫描书库。应用容器由 Docker 的 `unless-stopped` 策略恢复。Mac 需在登录时启动自己的 Docker 运行时。

## 找书与阅读

- 在「请求」输入书名，也可填作者或 ISBN。检查语言和版本，再选取得文件的来源。缺少书目结果时，使用页面提供的直接搜索来源操作。电子书请求包括漫画；音频使用有声书请求。下载由 BookOrbit 自带客户端完成。确认进入书库后，从书籍详情选择「阅读」或「听书」。
- 英语经典来自 Standard Ebooks，中文古籍扫描本来自 Wikimedia Commons 的台湾华文电子书库，有声书来自 LibriVox，漫画来自杜克大学法学院两部授权出版物。扫描件可能有多个版次；核对出版者、年代、馆藏编号和页数。识别信息不足的下载进入复核。[来源安装与验收](sources/README.md)
- 「找书与借阅 · 来源目录」是同一书架上的一本小册，收有 Oxford SOLO、中文维基文库、公共图书馆及其他发现渠道。馆藏与商业版本由供应商办理登录、借阅和授权。个人已有文件可从「书籍停靠站 / Book Dock」导入，或按每书一目录复制到 `books/Library` 后从库设置发起扫描。
- 工作台默认保留文件内的版本信息；可以在单册详情手动匹配元数据。自动抓取未开启，读者选择具体版本。已配置的渠道可以从服务器设置的请求页面维护。网页来源在实例的 `channels.json` 编辑，用下面的命令更新小册，再扫描书库。

```sh
python3 channel_guide.py "$instance/channels.json" "$instance/books/Library/找书与借阅 · 来源目录/找书与借阅 · 来源目录.epub"
```

## 数据、备份与恢复

| 内容 | 拥有者与可携带记录 |
| --- | --- |
| 图书文件 | 实例 `books/`。原文件可独立打开、复制及按哈希核验。 |
| 书目、来源设置、请求、个人进度、书签与笔记 | BookOrbit PostgreSQL。导出命令还会生成便于阅读的 JSON，含书目、具体文件、阅读位置、书签及有声书播放位置。 |
| 网站入口、插件、封面、服务密钥 | 实例 `channels.json`、`data/app/`、`.env` 与 `owner.json`。只有个人完整备份包含账户和密钥。 |
| 借阅权、学校身份、续借 | 登录学校或图书馆供应商，用具体馆藏链接恢复。 |

```sh
python3 backup.py export "$instance" "$HOME/Downloads/bookorbit-records.json"
python3 backup.py backup "$instance"
python3 backup.py restore "/path/to/bookorbit-backup.tar.gz" "/path/to/empty-directory" --project shelf-restore --port 8821
```

备份先导出可读记录，再短暂停止应用，使数据库转储和书库文件对应同一次静止状态，完成后恢复服务。归档写入实例的 `backups/`。将归档另存到个人备份介质。恢复使用空目录、独立 Compose 项目名和空闲端口，原有实例可继续工作。核对书目、来源、附件和续读位置后可关闭演练副本。在恢复目录执行 `docker compose down`。

## 版本与开发

本配置直接运行 BookOrbit 官方镜像。来源插件可独立发布和安装。要修改 BookOrbit 自身的检索、界面或阅读器，在同一 Fork 中改 `client/`、`server/` 或 `packages/`，按上游测试和署名要求制作派生镜像，经隔离验收后替换 Compose 的镜像摘要。GitHub 代码提交与 Mac 上线分开操作。Fork 的开发约定及升级流程见 [AGENTS.md](AGENTS.md)。[上游许可证与附加条款](../../ADDITIONAL_TERMS.md)
