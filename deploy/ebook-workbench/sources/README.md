# BookOrbit 公开电子书来源

初版的三个自有 BookOrbit 3.10.0 插件均使用 `@bookorbit/plugin-api` 契约 1，获取的是来源提供的原文件。中文以台湾华文电子书库的公版扫描为起点，英文使用 Standard Ebooks 的公开单册目录，漫画使用杜克大学法学院公共领域研究中心的两种授权作品。来源页保留版次、署名和授权依据。书库、下载状态和阅读进度由 BookOrbit 管理。[上游插件契约](https://github.com/bookorbit/bookorbit/blob/v3.10.0/packages/plugin-api/src/index.ts)

| 来源类型                  | 基础地址                        | 支持范围                                                        | 样本查询                                                  |
| ------------------------- | ------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------- |
| `wikimedia-commons-books` | `https://commons.wikimedia.org` | 有书名与中文语言元数据、标为公有领域的台湾华文电子书库 PDF 扫描 | `唐诗三百首` 或 `唐詩三百首`                              |
| `standard-ebooks`         | `https://standardebooks.org`    | 英语公众目录，每次手选一册，取得常规 EPUB                       | `Pride and Prejudice`，Jane Austen                        |
| `duke-open-comics`        | `https://cspd.law.duke.edu`     | Duke Law CSPD 英语授权漫画，人工核验的两种作品                  | `Bound by Law`（CBZ）；`Theft! A History of Music`（PDF） |

## 安装与维护

进入 BookOrbit 的 **Settings → Server → Requests → Sources**，用 **Install plugin** 分别上传各子目录内的 `index.mjs`。也可把文件放在 `$APP_DATA_PATH/plugins/indexers/<来源类型>/index.mjs`，由启动时的插件加载器读取。BookOrbit 3.10.0 的 Docker 默认 `APP_DATA_PATH=/data`。插件载入后分别添加并启用来源，采用表中的地址，`allowPrivateAddress=false`。来源均可匿名使用，直链由 BookOrbit 内置下载器下载。中文来源有可选的 `operatorContact`。若部署用于自动化检索，填能够联系到操作者的 Wikimedia 用户页、邮箱或网站，并以低频使用。[上游 Requests 说明](https://bookorbit.app/book-requests/) · [Wikimedia API 使用指引](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines/en)

经常自行找书和取书的账号需要 Request books 与 Download books directly 权限。书目结果用 Choose release 打开版本清单。若书目索引没有命中，自助取书账号可直接用输入的题名搜索已启用的获取来源。[自助下载与权限](https://bookorbit.app/book-requests/#downloading-without-asking)

中文用繁体检索接口查询台湾华文电子书库。简体题名通过 Wikimedia 的中文变体转换再检索。候选保留来源所列的出版者、版本、卷册、年份和扫描号，便于区分同名结果。正文语言来自文件书目记录。Standard Ebooks 用公开网页的结构化书名和作者信息查找单册，选择后读取该册常规 EPUB 链接和公开下载确认页，校验最终链接与该册路径一致。联网操作统一使用 BookOrbit 提供的插件网络接口。收到 429 或来源要求等待时，界面会收到节流错误。[MediaWiki 中文变体转换](https://www.mediawiki.org/wiki/Writing_systems/LanguageConverter) · [Standard Ebooks 馆藏范围](https://standardebooks.org/contribute/collections-policy)

同仓检视的上游公开插件包括有声书 LibriVox 和 Project Gutenberg。Gutenberg 适配器使用 OPDS 搜索，普通自动客户端访问规则使它暂不适合本机采用。台湾华文电子书库只覆盖该馆藏，Standard Ebooks 主要是英语公版，馆藏借阅、身份认证及商业版本由各自的服务处理。[上游公开插件清单](https://github.com/orbit-plugins/bookorbit-open-plugins/tree/f7e1992404251e7c34f86755940932edc6c744bf) · [Gutenberg 自动访问规则](https://www.gutenberg.org/policy/robot_access.html) · [Standard Ebooks 馆藏与订阅说明](https://standardebooks.org/feeds)

### 漫画来源

BookOrbit 3.10.0 的漫画使用 Requests 里的电子书（`ebook`）类型，选择 CBZ 版本即可走内置下载与漫画阅读器。杜克适配器根据题名查询两本核对过的作品，返回原始出处和作者。第一本使用杜克官方发布的 JPEG ZIP，仅以 `.cbz` 扩展名进入 BookOrbit，不改 ZIP 或画面字节。第二本保留出版社提供的 PDF。书源页记载两书的署名、非商业使用和相同方式共享条款。[BookOrbit 请求类型源码](https://github.com/bookorbit/bookorbit/blob/v3.10.0/packages/types/src/book-request.ts) · [Duke CSPD 官方出版物](https://cspd.law.duke.edu/publications/)

Digital Comic Museum 和 Comic Book Plus 提供古典漫画，取得下载需要站点账号，可作为网页渠道。David Revoy 的《小辣椒与萝卜头》（_Pepper&Carrot_）可从作者站直接阅读简体中文版。作者站公开 CC BY 4.0 的分集简体渲染图、语言 API 与逐集翻译者署名。该 API 以单页图像提供分集，当前直链适配器按单文件下载。[Digital Comic Museum](https://digitalcomicmuseum.com/) · [Comic Book Plus](https://comicbookplus.com/) · [小辣椒与萝卜头](https://www.peppercarrot.com/cn/) · [作者授权页](https://www.peppercarrot.com/cn/about/index.html) · [分集 API](https://www.peppercarrot.com/en/documentation/130_API.html)

## 2026-11-25 来源验收

Mac 隔离验证使用插件的 `test`、`search` 和 `resolveFile`，以 JavaScript `fetch` 模拟插件宿主，再用 BookOrbit 内置下载客户端使用的 `User-Agent: BookOrbit` 获取来源文件。以下原文件均返回 HTTP 200。以本次文件为基线，来源重制电子版后文件大小和散列可能变化。

| 样本及版本                                                                                                                                                                                                                                        | 文件与正文                                                                                                                                                                                                        | SHA-256                                                            |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| 蘅塘退士编《唐詩三百首》，商務印書館第十一版，1947，`NCL-004458562`。Commons 标为 Public domain，台湾国家图书馆藏本和影像。简体题名返回 13 条，验收按扫描号选择。[书源文件页](https://commons.wikimedia.org/wiki/Special:Redirect/page/126056711) | `application/pdf`，30,665,327 字节，162 页。第 12 页渲染读到竖排繁体诗文。                                                                                                                                        | `e9dcfc45839596240da9aca065e0b0c2b68a861f4440815465c48b4c59308281` |
| Jane Austen，_Pride and Prejudice_，Standard Ebooks 版。书页写明 CC0 贡献许可，搜索返回 1 条。[书源版本页](https://standardebooks.org/ebooks/jane-austen/pride-and-prejudice) · [公开授权说明](https://standardebooks.org/about)                  | `application/epub+zip`，831,931 字节。ZIP 文件结构、`mimetype`、OPF 作者与 `en-GB`、首章英语正文已验。                                                                                                            | `bc41e616c102d33c4c37b91baaa0c87af9c73838f32d4c75c600939b1c7ea587` |
| Keith Aoki、James Boyle、Jennifer Jenkins，_Tales from the Public Domain: Bound by Law?_。CC BY-NC-SA 2.5。[杜克官方文件页](https://cspd.law.duke.edu/comics/digital/) · [许可](https://creativecommons.org/licenses/by-nc-sa/2.5/)               | `application/zip`，9,554,441 字节。以 `Bound by Law.cbz` 原字节读取。ZIP CRC 校验、BookOrbit v3.10.0 的 CBZ 签名检测及原生解析器读取全部 72 张 JPEG 均通过。按上游排序，许可页先于封面，随后为正文第 1 至 70 页。 | `0fa80c39beda708a50b071e061dc837b85eac02d84e742f7982504f7719645cd` |
| James Boyle、Jennifer Jenkins、Keith Aoki，_Theft! A History of Music_，公开整书 PDF。CC BY-NC-SA 3.0 US。[杜克官方文件页](https://cspd.law.duke.edu/musiccomic/download/) · [许可](https://creativecommons.org/licenses/by-nc-sa/3.0/us/)        | `application/pdf`，78,273,512 字节，263 页，HTTP 200。                                                                                                                                                            | `ad8366a777955316d01e65d8b3db4573b489975beb315ecf1d4125a1f99f06aa` |

三个模块均通过 `node --check`。错误基础地址、异常文件地址和 HTTP 429 都返回错误。漫画以 `ebook` 查找、解析到固定发布地址和 `.cbz` 文件名，旧的 `comic` 类型、音频和未收录书名均返回空。以上是适配器与文件核验。服务内界面验收使用这些样本，验证选择来源、意图确认、导入和原生阅读。

## 独立上游的有声书插件

随配置附带的第四枚插件为 LibriVox 1.1.0。其源码与 MIT 许可证取自固定提交，SHA-256 为 `93aff79339edc7968b95a38c02c253f7c3e9f3edbb9c22cdbb581ce2828ede71`。BookOrbit 通过 LibriVox 目录取得音轨压缩包并入库，按录音语言和朗读者选版。[固定上游](https://github.com/orbit-plugins/bookorbit-open-plugins/tree/f7e1992404251e7c34f86755940932edc6c744bf/indexers/librivox)

## 原版 EPUB 和中文分章小说

Requests 的 **Project Gutenberg · EPUB 原件** 使用本机书目索引检索图书，核验基金会镜像实际列出的 EPUB，返回文件给 BookOrbit。例为《西遊記》编号 23962。[版本记录](https://www.gutenberg.org/ebooks/23962)

**中文小说 · 完整章节 EPUB** 从已核验的固定上游生成整书后才列出版本。现有《老殘遊記》自敘及二十回，另有独立简体译本《雪月》32 章。书内保留版次、署名和许可。两项来源均可用 `file_sources.py` 安装。[章节生成与来源](../chapter-books/README.md)
