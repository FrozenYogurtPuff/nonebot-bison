from datetime import datetime
import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup as bs
import httpx
from nonebot import logger

from ..post import Post
from ..types import *
from .platform import Platform

class Weibo(Platform):

    categories = {
            1: '转发',
            2: '视频',
            3: '图文',
            50: '撤置顶'
        }
    enable_tag = False
    platform_name = 'weibo'

    def __init__(self):
        self.top : dict[Target, RawPost] = dict()
        super().__init__()

    @staticmethod
    async def get_account_name(target: Target) -> Optional[str]:
        async with httpx.AsyncClient() as client:
            param = {'containerid': '100505' + target}
            res = await client.get('https://m.weibo.cn/api/container/getIndex', params=param)
            res_dict = json.loads(res.text)
            if res_dict.get('ok') == 1:
                return res_dict['data']['userInfo']['screen_name']
            else:
                return None

    async def get_sub_list(self, target: Target) -> list[RawPost]:
        async with httpx.AsyncClient() as client:
            params = { 'containerid': '107603' + target}
            res = await client.get('https://m.weibo.cn/api/container/getIndex?', params=params, timeout=4.0)
            res_data = json.loads(res.text)
            if not res_data['ok']:
                return []
            return res_data['data']['cards']

    def get_id(self, post: RawPost) -> Any:
        if post.get('_type'):
            return None
        return post['mblog']['id']

    def filter_platform_custom(self, raw_post: RawPost) -> bool:
        return raw_post['card_type'] == 9

    def get_date(self, raw_post: RawPost) -> float:
        created_time = datetime.strptime(raw_post['mblog']['created_at'], '%a %b %d %H:%M:%S %z %Y')
        return created_time.timestamp()

    def get_tags(self, raw_post: RawPost) -> Optional[list[Tag]]:
        "Return Tag list of given RawPost"
        return None

    def get_category(self, raw_post: RawPost) -> Category:
        if (custom_cat := raw_post.get('_type')):
            return Category(custom_cat)
        if raw_post['mblog'].get('retweeted_status'):
            return Category(1)
        elif raw_post['mblog'].get('page_info') and raw_post['mblog']['page_info'].get('type') == 'video':
            return Category(2)
        else:
            return Category(3)

    def _get_text(self, raw_text: str) -> str:
        text = raw_text.replace('<br />', '\n')
        return bs(text, 'html.parser').text

    def _get_top(self, raw_post_list: list[RawPost]) -> Optional[RawPost]:
        for raw_post in raw_post_list:
            if raw_post['card_type'] == 9:
                if raw_post['mblog'].get('isTop'):
                    return raw_post
        return None

    async def filter_common(self, target: Target, raw_post_list: list[RawPost]) -> list[RawPost]:
        if not self.inited.get(target, False):
            self.top[target] = self._get_top(raw_post_list)
            await super().filter_common(target, raw_post_list)
            return []
        else:
            new_post = self._get_top(raw_post_list)
            res = await super().filter_common(target, raw_post_list)
            if (self.top[target] is not None and new_post is None) or \
                    (self.top[target] is not None and new_post is not None and self.get_id(self.top[target]) != self.get_id(new_post)):
                if new_post:
                    logger.info('cancel top: {}'.format(new_post))
                else:
                    logger.info('cancel top: {}'.format(raw_post_list))
                res.append({'_type': 50, 'target': self.top[target]['mblog']['user']['screen_name']})
            self.top[target] = new_post
            return res

    async def parse(self, raw_post: RawPost) -> Post:
        if raw_post.get('_type') == 50:
            # cancel top
            return Post('weibo', text="撤置顶", url='', pics=[], target_name=raw_post['target'], override_use_pic=False)
        info = raw_post['mblog']
        if info['isLongText'] or info['pic_num'] > 9:
            async with httpx.AsyncClient() as client:
                res = await client.get('https://m.weibo.cn/detail/{}'.format(info['mid']))
            full_json_text = re.search(r'"status": ([\s\S]+),\s+"hotScheme"', res.text).group(1)
            info = json.loads(full_json_text)
        parsed_text = self._get_text(info['text'])
        pic_urls = [img['large']['url'] for img in info.get('pics', [])]
        detail_url = 'https://weibo.com/{}/{}'.format(info['user']['id'], info['bid'])
        # return parsed_text, detail_url, pic_urls
        return Post('weibo', text=parsed_text, url=detail_url, pics=pic_urls, target_name=info['user']['screen_name'])
