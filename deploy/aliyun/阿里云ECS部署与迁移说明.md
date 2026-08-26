# 《甲骨里的日光缺口》阿里云 ECS 部署与迁移说明

## 1. 部署目标

本部署包用于将公众站、参赛入口和需要登录的研究工作台部署到一台独立的阿里云 ECS。默认结构如下：

```text
互联网 -> 阿里云安全组 80/443 -> Nginx HTTPS -> 127.0.0.1:8018
                                                    -> Python应用
                                                    -> 私有SQLite/PDF/生成媒体
                                                    -> 阿里云百炼HTTPS接口
```

应用端口`8018`只监听本机，原始 PDF、SQLite、历史版本、脚本和密钥均由 Nginx 与应用双重阻止公开访问。

## 2. ECS 选择

- 推荐：Ubuntu 22.04 LTS、x86_64、2核4GB、60GB ESSD、5Mbps以上公网带宽。
- 已备案域名：优先选择杭州、上海、青岛或北京地域，访问百炼延迟更低。
- 未备案域名：选择阿里云香港地域；中国大陆地域的网站域名必须先完成ICP备案。
- 部署前创建系统盘快照，开启云监控、磁盘告警和百炼额度告警。

本包同时兼容 Ubuntu 24.04 和 ARM64，但比赛演示优先使用 Ubuntu 22.04 x86_64，第三方 Python 依赖兼容性更稳定。

## 3. 安全组

仅配置以下入方向规则：

| 端口 | 来源 | 用途 |
|---|---|---|
| 22/TCP | 管理员固定公网IP/32 | SSH管理 |
| 80/TCP | 0.0.0.0/0、::/0 | 证书签发及HTTPS跳转 |
| 443/TCP | 0.0.0.0/0、::/0 | 正式网站 |

不要开放`8018`、数据库、Redis、Docker、宝塔或其他管理端口。若管理员没有固定 IP，可在安装期间临时开放 22，完成后立即收紧。

## 4. 部署包内容

压缩包包含当前公众内容、研究数据库、7篇核心资料、OCR页、已生成媒体和源码，不包含真实 API Key、登录密码、Git 历史、日志、缓存和历史数据库备份。

重要目录：

```text
deploy/aliyun/install.sh              安装系统依赖、应用、Nginx和systemd
deploy/aliyun/configure-secrets.sh    隐藏输入研究账号和百炼Key
deploy/aliyun/verify.sh               上线自动验收
deploy/aliyun/backup.sh               一致性数据备份
source-materials/                     私有资料、数据库和媒体
data/published-snapshot.json          当前公众发布版本
```

## 5. 上传与校验

在本机将部署包和校验文件上传到 ECS：

```bash
scp oracle-eclipse-mvp-aliyun-20260726.tar.gz root@ECS公网IP:/root/
scp oracle-eclipse-mvp-aliyun-20260726.tar.gz.sha256 root@ECS公网IP:/root/
```

登录 ECS 后校验并解压：

```bash
cd /root
sha256sum -c oracle-eclipse-mvp-aliyun-20260726.tar.gz.sha256
mkdir -p /root/oracle-eclipse-deploy
tar -xzf oracle-eclipse-mvp-aliyun-20260726.tar.gz -C /root/oracle-eclipse-deploy
cd /root/oracle-eclipse-deploy/oracle-eclipse-mvp
```

校验结果必须为`OK`。校验失败时不要继续部署，应重新上传。

## 6. 安装应用

以下命令安装到`/opt/oracle-eclipse/app`，建立独立的低权限账号，并配置只监听本机`8018`的服务：

```bash
sudo bash deploy/aliyun/install.sh sci.ljcode.cn
```

安装脚本不会保存真实密钥，也不会在密钥未配置时启动应用。随后通过隐藏输入设置全新的研究账号密码和已轮换的百炼 API Key：

```bash
sudo bash /opt/oracle-eclipse/app/deploy/aliyun/configure-secrets.sh sci.ljcode.cn
```

密钥保存在`/etc/oracle-eclipse/oracle-eclipse.env`，权限为`600`，不要复制回网站目录、Git、PPT或聊天记录。

先进行本机和HTTP检查：

```bash
systemctl status oracle-eclipse --no-pager
curl --fail http://127.0.0.1:8018/api/health
curl --fail -H 'Host: sci.ljcode.cn' http://ECS公网IP/api/health
```

## 7. DNS 与 HTTPS 切换

1. 提前把`sci.ljcode.cn`的 DNS TTL 调为 600 秒。
2. 停止旧服务器上的研究写入，完成最后一次数据备份，避免两台服务器同时编辑形成分叉。
3. 把域名 A 记录改为新 ECS 公网 IP；如未配置 IPv6，不要保留旧 AAAA 记录。
4. 等待解析生效后签发证书：

```bash
getent hosts sci.ljcode.cn
sudo certbot --nginx -d sci.ljcode.cn --redirect --agree-tos --no-eff-email -m 你的邮箱
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
```

Nginx 默认不启用 HTTP/2。确认系统 Nginx 已应用安全更新后，可以在维护窗口单独评估是否启用。

## 8. 自动与人工验收

自动验收：

```bash
sudo bash /opt/oracle-eclipse/app/deploy/aliyun/verify.sh sci.ljcode.cn
```

还必须在桌面浏览器和手机流量下人工完成：

- 打开公众站、`/showcase/`和在线技术报告。
- 登录`/research/`，确认登录后立即显示最新数据。
- 打开PDF详情并测试页码联动。
- 完成一次公众问答、资料问答和作品生成。
- 播放音频导览，翻页查看图卡和幻灯片。
- 批准一个测试作品、发布测试版本，并确认公众端更新。
- 验证`/source-materials/research.db`和任意原始PDF返回404。

## 9. 当前包与最终迁移数据

部署包是生成时刻的数据快照。若韩国服务器在此后仍发生资料导入、作品修改或发布，需要在正式切换前重新迁移以下内容：

```text
source-materials/research.db
source-materials/pdfs/
source-materials/imports/
source-materials/generated/
source-materials/site-assets/
data/published-snapshot.json
data/release-history/
```

迁移 SQLite 时必须先停止旧服务器应用，复制完成后再启动新服务器；不要在两台服务器同时修改数据库。

## 10. 备份、更新与回滚

创建一致性备份：

```bash
sudo bash /opt/oracle-eclipse/app/deploy/aliyun/backup.sh
ls -lh /var/backups/oracle-eclipse/
```

代码更新前先备份。保留服务器上的`source-materials/`、`data/`和`/etc/oracle-eclipse/oracle-eclipse.env`，不要用新压缩包直接覆盖这三处。更新后执行：

```bash
sudo systemctl restart oracle-eclipse
sudo bash /opt/oracle-eclipse/app/deploy/aliyun/verify.sh sci.ljcode.cn
```

更新失败时停止服务，恢复上一个代码目录和最近的数据备份，再启动服务。阿里云系统级故障优先通过部署前的系统盘快照回滚。

## 11. 百炼与比赛期间运行

- ECS 只需允许出方向 HTTPS 443 到`dashscope.aliyuncs.com`，无需为百炼开放入方向端口。
- 在研究工作台顶部执行一次模型连接检测，状态应显示`百炼 · qwen-plus`。
- 为比赛单独创建百炼 API Key，并设置费用额度与告警；比赛结束后轮换或禁用。
- 提前一天完成至少2小时连续运行测试，并准备1080P本地演示视频作为网络降级方案。
- 评审期间冻结重要资料删除和大规模OCR任务，避免占满CPU、磁盘或百炼并发额度。

## 12. 常用命令

```bash
systemctl status oracle-eclipse --no-pager
systemctl restart oracle-eclipse
journalctl -u oracle-eclipse -n 100 --no-pager
nginx -t && systemctl reload nginx
certbot certificates
df -h /
```

真实密码、API Key、Cookie、原始论文和研究数据库不得写入日志或公开下载目录。
