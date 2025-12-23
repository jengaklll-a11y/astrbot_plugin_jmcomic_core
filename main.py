import time
import requests
from astrbot.api.all import *

@register("jm_cosmos", "Oasis Akari", "精简版 JM Cosmos 插件", "1.0.2")
class Main(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.client_id = self.config.get("client_id")
        self.client_secret = self.config.get("client_secret")
        self.access_token = None
        self.token_expires = 0
        self.base_url = "https://api.jm.cosmos.link"

    def _get_token(self):
        """内部方法：获取或刷新 Access Token"""
        if self.access_token and time.time() < self.token_expires:
            return self.access_token

        url = f"{self.base_url}/oauth2/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        try:
            self.context.logger.info("正在刷新 JM Cosmos Access Token...")
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            # 提前 60 秒认为过期，防止临界点请求失败
            self.token_expires = time.time() + token_data["expires_in"] - 60
            self.context.logger.info("Access Token 刷新成功。")
            return self.access_token
        except Exception as e:
            self.context.logger.error(f"获取 Token 失败: {e}")
            raise Exception("身份验证失败，请检查 client_id 和 client_secret 是否正确。")

    def _request(self, method, endpoint, **kwargs):
        """内部方法：统一的 HTTP 请求处理"""
        if not self.client_id or not self.client_secret:
             raise Exception("未配置 client_id 或 client_secret，请先在配置中填写。")

        token = self._get_token()
        url = f"{self.base_url}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        # 设置默认超时
        kwargs.setdefault("timeout", 15)

        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200:
                return data.get("data")
            else:
                raise Exception(f"API 错误 [{data.get('code')}]: {data.get('msg')}")
        except requests.exceptions.RequestException as e:
            self.context.logger.error(f"网络请求失败: {e}")
            raise Exception(f"网络请求失败: {e}")
        except Exception as e:
            self.context.logger.error(f"请求处理失败: {e}")
            raise

    @command("jm搜")
    async def jm_search(self, event: AstrMessageEvent, query: str):
        """搜索 JM Cosmos 资源。用法：/jm搜 <关键词>"""
        if not query:
            yield event.plain_result("请输入搜索关键词。")
            return

        try:
            # 仅调用搜索 API，不再嵌套调用详情 API
            data = self._request("GET", "/search", params={"cn": query})
            content = data.get("content", [])
            if not content:
                yield event.plain_result("未找到相关资源。")
                return

            msg = ["搜索结果："]
            for item in content:
                # 仅展示搜索结果中直接可用的信息
                msg.append(f"ID: {item.get('id')} | 标题: {item.get('title')} | 作者: {item.get('author')}")
            
            yield event.plain_result("\n".join(msg))

        except Exception as e:
            yield event.plain_result(f"搜索失败：{e}")

    @command("jm看")
    async def jm_detail(self, event: AstrMessageEvent, resource_id: str):
        """查看资源详情。用法：/jm看 <资源ID>"""
        if not resource_id:
            yield event.plain_result("请输入资源 ID。")
            return

        try:
            data = self._request("GET", f"/detail/{resource_id}")
            if not data:
                 yield event.plain_result("未找到该资源详情。")
                 return

            # 数据处理
            tags = ", ".join([tag["name"] for tag in data.get("tags", [])]) if data.get("tags") else "无"
            works = ", ".join([work["name"] for work in data.get("works", [])]) if data.get("works") else "无"
            description = data.get('des', '无描述')
            
            # 构建图文消息链
            msg_chain = [
                Plain(f"标题：{data.get('title')}\n"),
                Plain(f"作者：{data.get('author')}\n"),
                Plain(f"标签：{tags}\n"),
                Plain(f"作品来源：{works}\n"),
                Plain(f"描述：{description}\n"),
            ]
            
            cover_url = data.get("cover")
            if cover_url:
                # 将封面图放在最前面
                msg_chain.insert(0, Image.fromURL(cover_url))

            yield event.chain_result(msg_chain)

        except Exception as e:
            yield event.plain_result(f"获取详情失败：{e}")
