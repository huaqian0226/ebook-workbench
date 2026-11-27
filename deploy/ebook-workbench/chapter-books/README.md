# 中文分章电子书

BookOrbit 的「请求」可按题名搜索这个来源，并取得已经验证的整本 EPUB。书源首次启动时从固定上游修订生成文档。本地缓存由服务维护。每本书独立准备，某一来源暂时不可用时，已准备好的书仍可搜索。

## 收录版次

| 书名                       | 正文、语言和来源                                                                                                                                                                                                                                                                                                                                                                       |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 《老殘遊記》或「老残游记」 | 刘鹗，繁体中文。维基文库目录所列 1907 年原作，含自叙和二十回，续集另有书目。原作属公有领域，EPUB 以 CC BY-SA 4.0 提供维基转录的改编，并附目录和各章固定修订链接。[作品目录](https://zh.wikisource.org/w/index.php?oldid=12704905) · [作者与版权声明](<https://zh.wikisource.org/wiki/Author:%E5%8A%89%E9%B6%9A_(%E6%B8%85)>) · [许可](https://creativecommons.org/licenses/by-sa/4.0/) |
| 《雪月》或「Snowmoon」     | Vitalik Buterin 原作，独立简体中文机器辅助译本，共 32 章，含上游章节表格和 SVG 图。EPUB 附原作、固定提交、完整对应源文件和 GPLv3 通知。[原作](https://vitalik.eth.limo/snowmoon/) · [译本与完整源码](https://github.com/sdsunqian/Snowmoon/tree/d11edb183ec0c1e41f8e02b939047b68c3b55793)                                                                                              |

## 服务与维护

- BookOrbit 插件位于 [sources/chapter-books/index.mjs](../sources/chapter-books/index.mjs)，应用配置使用 `http://chapter-books:8080`，并启用该源的 **Allow private address**。
- `GET /healthz` 给出已准备的书数。至少有一本可用时返回 200。`GET /search?q=<题名>` 返回当前可取的版次。`GET` 或 `HEAD /books/<slug>/<editionId>.epub` 取得或检查对应 EPUB。
- Docker 使用本目录作为构建上下文。容器账户为 `65532:65532`，缓存目录为 `/chapter-cache`，只有整书通过校验后才会写入 `<slug>-<editionId>.epub`。应用容器只读挂载同一卷。缓存用作取件，已入书架的文件和阅读进度由 BookOrbit 保存。
- 收录新书或切换版次之前，查实对应正文、完整目录、离线保存及再分发条款，再固定上游修订和内容校验值。任何正文或打包版次变更都要更新 `editionId`，使已发出的文件地址对应原有版本。查看准备日志即可定位上游不可用、正文校验失败或 EPUB 损坏。服务重启时优先读回已完成的缓存。
- 从仓库根目录运行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s deploy/ebook-workbench/chapter-books -v` 和 `node --test deploy/ebook-workbench/chapter-books/test_plugin.mjs`。全书顺序、缺章或截断拒发、单源不可用时另一源继续工作、版次 URL 和 EPUB 文件类型都有覆盖。

隔离 Docker 验收从两条上游实际生成 EPUB，经插件搜索、确认版次、取件和正文检查后重启容器读回同一缓存。古典样本含 21 个正文文档和 22 个可跳转目录项。现代样本含 32 个正文文档、33 个可跳转目录项、69 张表格和 56 个内嵌 SVG。两套目录均含署名页，两份 EPUB 均通过 EPUBCheck 5.4.0，零错误、零警告。
