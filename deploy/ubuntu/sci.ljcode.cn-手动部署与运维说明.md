# sci.ljcode.cn 手动部署与运维说明

## 1. 为什么宝塔项目列表中看不到

`sci.ljcode.cn`采用`systemd + Nginx`手动部署，没有写入宝塔内部的 Python 项目数据库，因此不会显示在宝塔“Python项目”列表中。网站仍使用宝塔安装的 Nginx，配置文件也位于宝塔目录内。

不要在宝塔中再次新建同域名 Python 项目，否则可能产生重复进程、端口冲突或覆盖现有 Nginx 配置。如需改为宝塔托管，应先备份并停止当前 systemd 服务，再迁移配置。

## 2. 当前运行位置

```text
项目目录        /www/wwwroot/oracle-eclipse-mvp
Python环境      /www/wwwroot/oracle-eclipse-mvp/.venv
后台服务        oracle-eclipse.service
本机监听        127.0.0.1:8018
域名            https://sci.ljcode.cn
Nginx配置       /www/server/panel/vhost/nginx/sci.ljcode.cn.conf
运行环境变量    /etc/oracle-eclipse/oracle-eclipse.env
证书目录        /etc/letsencrypt/live/sci.ljcode.cn
```

应用端口只监听本机，不应在宝塔安全组或云防火墙开放`8018`。

## 3. 常用管理命令

```bash
systemctl status oracle-eclipse --no-pager
systemctl restart oracle-eclipse
systemctl stop oracle-eclipse
systemctl start oracle-eclipse
journalctl -u oracle-eclipse -n 100 --no-pager
journalctl -u oracle-eclipse -f
```

修改 Nginx 配置后必须先检查再重载：

```bash
nginx -t && systemctl reload nginx
```

## 4. 账号和百炼配置

密钥文件只有 root 可读，不要在宝塔网站目录、Git或日志中保存真实密码和 API Key。

通过隐藏输入更新配置：

```bash
bash /www/wwwroot/oracle-eclipse-mvp/deploy/ubuntu/configure-secrets.sh sci.ljcode.cn
```

完成后检查：

```bash
curl --fail http://127.0.0.1:8018/api/health
```

返回结果中的`mode`应为`qwen`。

## 5. 数据与备份

必须备份：

```text
/www/wwwroot/oracle-eclipse-mvp/source-materials/research.db
/www/wwwroot/oracle-eclipse-mvp/source-materials/pdfs/
/www/wwwroot/oracle-eclipse-mvp/source-materials/imports/
/www/wwwroot/oracle-eclipse-mvp/source-materials/generated/
/www/wwwroot/oracle-eclipse-mvp/source-materials/site-assets/
/www/wwwroot/oracle-eclipse-mvp/data/published-snapshot.json
/www/wwwroot/oracle-eclipse-mvp/data/release-history/
```

备份 SQLite 前先短暂停止服务，复制完成后立即启动，避免得到不一致的数据库副本。

```bash
systemctl stop oracle-eclipse
cp source-materials/research.db /安全备份目录/research-$(date +%Y%m%d-%H%M%S).db
systemctl start oracle-eclipse
```

原始 PDF、数据库、历史版本和环境变量不得放入公众下载目录。

## 6. 更新代码

公众端使用 WebP 图片和 MP3 音频派生文件减少加载量，原始 PNG、WAV 继续作为研究母版和高质量下载。服务器需安装 FFmpeg：

```bash
apt-get update && apt-get install -y ffmpeg
```

1. 先备份数据库、发布版本和媒体目录。
2. 上传新版本到临时目录，不直接覆盖运行中的数据库和私有文件。
3. 保留服务器的`source-materials/`、`data/`和`/etc/oracle-eclipse/oracle-eclipse.env`。
4. 执行 Python 语法检查和必要测试。
5. 替换代码后重启服务并检查公网入口。

```bash
systemctl restart oracle-eclipse
curl --fail http://127.0.0.1:8018/api/health
curl --fail https://sci.ljcode.cn/api/health
```

## 7. HTTPS续期

证书由 Certbot 管理，有效证书路径保持不变，定时器已启用：

```bash
systemctl status certbot.timer --no-pager
certbot certificates
certbot renew --dry-run
```

续期后部署钩子会检查并重载 Nginx：

```text
/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

## 8. 上线检查

```text
https://sci.ljcode.cn/                              公众站
https://sci.ljcode.cn/showcase/                     参赛入口
https://sci.ljcode.cn/showcase/technical-report.html 技术报告
https://sci.ljcode.cn/research/                     研究工作台
```

应确认：HTTP自动跳转HTTPS、研究工作台要求登录、原始PDF和数据库返回404、百炼连接测试成功、手机网络可访问。

## 9. 本次处理的旧Nginx配置

服务器原有的11个失效站点配置已备份到：

```text
/www/server/panel/vhost/nginx-disabled/20260726/
```

`zzm.ljcode.cn`仍在运行，其证书已重新签发并改为 Certbot 自动续期路径。恢复任何旧配置前，必须先恢复对应后端和有效证书，再运行`nginx -t`。

## 10. Docker日志空间

本次部署前 Docker JSON 日志曾占用约56GB。当前轮转规则为每个日志50MB、保留3份：

```text
/etc/logrotate.d/docker-containers
```

定期检查：

```bash
df -h /
du -sh /var/lib/docker/containers
```
