import os
import time
import xml.dom.minidom
import requests
import base64
import json
from urllib.parse import urljoin
from typing import Dict, Any, List, Optional, Tuple

from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.utils.http import RequestUtils

class Prowlarr(_PluginBase):
    """
    Prowlarr 搜索器插件 - 专为MoviePilot V2版本设计
    """
    # 插件名称
    plugin_name = "Prowlarr"
    # 插件描述
    plugin_desc = "支持 Prowlarr 搜索器，将Prowlarr索引器添加到MoviePilot V2内建搜索器中。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Prowlarr/Prowlarr/refs/heads/develop/src/Prowlarr.ico"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "TDHXNP"
    # 作者主页
    author_url = "https://github.com/TDHXNP"
    # 插件配置项ID前缀
    plugin_config_prefix = "prowlarr_"
    # 加载顺序
    plugin_order = 21
    # 可使用的用户级别
    user_level = 1

    # 私有属性
    _enabled = False
    _host = None
    _api_key = None
    _indexers = None
    _added_indexers = []
    # 会话信息
    _session = None
    _cookies = None

    def init_plugin(self, config: dict = None) -> None:
        """
        插件初始化
        """
        self.siteshelper = SitesHelper()
        
        if config:
            # 读取配置
            self._enabled = config.get("enabled", False)
            self._host = config.get("host")
            self._api_key = config.get("api_key")
            self._indexers = config.get("indexers", [])
        
            # 初始化会话
            self._session = None
            self._cookies = None
            
            logger.info(f"【{self.plugin_name}】插件初始化完成，状态: {self._enabled}")

            if self._enabled and self._host and self._api_key:
                logger.info(f"【{self.plugin_name}】尝试添加Prowlarr索引器...")
                try:
                    self._add_prowlarr_indexers()
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】添加索引器异常: {str(e)}")
                    import traceback
                    logger.error(f"【{self.plugin_name}】异常详情: {traceback.format_exc()}")

    def get_state(self) -> bool:
        """
        获取插件状态
        """
        state = bool(self._enabled and self._host and self._api_key)
        logger.info(f"【{self.plugin_name}】get_state返回: {state}, enabled={self._enabled}, host={bool(self._host)}, api_key={bool(self._api_key)}")
        return state

    def get_form(self) -> Tuple[List[dict], dict]:
        """
        获取配置表单
        """
        return [
            {
                'component': 'VAlert',
                'props': {
                    'type': 'info',
                    'text': '配置Prowlarr服务器信息后，将自动导入Prowlarr中配置的索引器到MoviePilot搜索系统。请确保Prowlarr服务可以正常访问，并且已经配置了可用的索引器。',
                    'class': 'mb-4'
                }
            },
            {
                'component': 'VSwitch',
                'props': {
                    'model': 'enabled',
                    'label': '启用插件'
                }
            },
            {
                'component': 'VTextField',
                'props': {
                    'model': 'host',
                    'label': 'Prowlarr地址',
                    'placeholder': 'http://localhost:9117',
                    'hint': '请输入Prowlarr的完整地址，包括http或https前缀，不要以斜杠结尾'
                }
            },
            {
                'component': 'VTextField',
                'props': {
                    'model': 'api_key',
                    'label': 'API Key',
                    'type': 'password',
                    'placeholder': 'Prowlarr管理界面右上角的API Key'
                }
            },
            {
                'component': 'VSelect',
                'props': {
                    'model': 'indexers',
                    'label': '索引器',
                    'multiple': True,
                    'chips': True,
                    'items': [],
                    'hint': '留空则使用全部索引器，获取索引器前需保存基本配置'
                }
            }
        ], {
            "enabled": False,
            "host": "",
            "api_key": "",
            "password": "",
            "indexers": []
        }

    def get_page(self) -> List[dict]:
        """
        获取页面
        """
        return [
            {
                'component': 'VAlert',
                'props': {
                    'type': 'info',
                    'text': '此插件用于对接Prowlarr搜索器，将Prowlarr中配置的索引器添加到MoviePilot的内建索引中。需要先在Prowlarr中添加并配置好索引器，启用插件并保存配置后，即可在搜索中使用这些索引器。',
                    'class': 'mb-4'
                }
            }
        ]

    def get_api(self) -> List[dict]:
        """
        获取API接口
        """
        return [
            {
                "path": "/Prowlarr/indexers",
                "endpoint": self.get_indexers,
                "methods": ["GET"],
                "summary": "获取Prowlarr索引器列表",
                "description": "获取已配置的Prowlarr索引器列表"
            },
            {
                "path": "/Prowlarr/reload",
                "endpoint": self.reload_indexers,
                "methods": ["GET"],
                "summary": "重新加载Prowlarr索引器",
                "description": "重新加载Prowlarr索引器到MoviePilot"
            }
        ]

    def _fetch_prowlarr_indexers(self):
        """
        获取Prowlarr索引器列表
        """
        if not self._host or not self._api_key:
            logger.error(f"【{self.plugin_name}】缺少必要配置参数，无法获取索引器")
            return []
        
        # 规范化host地址
        if self._host.endswith('/'):
            self._host = self._host[:-1]
            
        try:
            # 设置请求头
            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": "MoviePilot/2.0",
                "X-Api-Key": self._api_key,
                "Accept": "application/json, text/javascript, */*; q=0.01"
            }
            
            # 创建session并设置headers
            session = requests.session()
            req = RequestUtils(headers=headers, session=session)
            
            # 获取索引器列表
            indexer_query_url = f"{self._host}/api/v1/indexer"
            response = req.get_res(
                url=indexer_query_url,
                verify=False
            )
            
            if response and response.status_code == 200:
                indexers = response.json()
                if indexers and isinstance(indexers, list):
                    logger.info(f"【{self.plugin_name}】成功获取到{len(indexers)}个索引器")
                    return indexers
                    
            return []
                
        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取Prowlarr索引器异常: {str(e)}")
            return []

    def _format_indexer(self, prowlarr_indexer):
        """
        将Prowlarr索引器格式化为MoviePilot V2索引器格式
        """
        try:
            # 从Prowlarr API返回的数据中提取必要信息
            indexer_id = prowlarr_indexer.get("id", "")
            indexer_name = prowlarr_indexer.get("name", "")
            base_url = f"{self._host}/api/v1/indexer/{indexer_id}"
            
            # 构建分类信息
            categories = {
                "movie": [],
                "tv": []
            }
            
            # 处理分类
            for category in prowlarr_indexer.get("capabilities", {}).get("categories", []):
                cat_id = category.get("id")
                cat_name = category.get("name")
                
                # 根据分类ID判断类型
                if cat_id in [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]:
                    categories["movie"].append({
                        "id": str(cat_id),
                        "cat": cat_name,
                        "desc": cat_name
                    })
                elif cat_id in [5000, 5020, 5030, 5040, 5050, 5060, 5070]:
                    categories["tv"].append({
                        "id": str(cat_id),
                        "cat": cat_name,
                        "desc": cat_name
                    })
            
            # 使用符合MoviePilot V2要求的索引器格式
            mp_indexer = {
                "id": f"prowlarr_{indexer_id.lower()}",
                "name": f"[Prowlarr] {indexer_name}",
                "domain": base_url,
                "encoding": "UTF-8",
                "public": prowlarr_indexer.get("privacy") == "public",
                "proxy": False,
                "category": categories,
                "search": {
                    "paths": [
                        {
                            "path": "/newznab",
                            "method": "get"
                        }
                    ],
                    "params": {
                        "t": "search",
                        "q": "{keyword}",
                        "cat": "{cat}",
                        "apikey": self._api_key,
                        "limit": 100,
                        "extended": 1
                    }
                },
                "torrents": {
                    "list": {
                        "selector": "item"
                    },
                    "fields": {
                        "id": {
                            "selector": "guid"
                        },
                        "title": {
                            "selector": "title"
                        },
                        "description": {
                            "selector": "description",
                            "optional": True
                        },
                        "details": {
                            "selector": "comments",
                            "optional": True,
                            "default": "guid"
                        },
                        "download": {
                            "selector": "link"
                        },
                        "size": {
                            "selector": "size"
                        },
                        "date_added": {
                            "selector": "pubDate"
                        },
                        "seeders": {
                            "selector": "torznab|attr[name=seeders]",
                            "default": "0"
                        },
                        "leechers": {
                            "selector": "torznab|attr[name=peers]",
                            "default": "0"
                        },
                        "grabs": {
                            "selector": "torznab|attr[name=grabs]",
                            "optional": True,
                            "default": "0"
                        },
                        "imdbid": {
                            "selector": "torznab|attr[name=imdbid]",
                            "optional": True
                        },
                        "downloadvolumefactor": {
                            "case": {
                                "torznab|attr[name=downloadvolumefactor]": "0",
                                "*": "1"
                            }
                        },
                        "uploadvolumefactor": {
                            "case": {
                                "torznab|attr[name=uploadvolumefactor]": "2",
                                "*": "1"
                            }
                        }
                    }
                }
            }
            
            logger.info(f"【{self.plugin_name}】已格式化索引器: {indexer_name}")
            return mp_indexer
        except Exception as e:
            logger.error(f"【{self.plugin_name}】格式化索引器失败: {str(e)}")
            return None

    def _remove_prowlarr_indexers(self):
        """
        从MoviePilot V2中移除Prowlarr索引器
        """
        try:
            # 移除已添加的索引器
            removed_count = 0
            for domain in self._added_indexers:
                try:
                    # 尝试使用新的API删除索引器
                    if hasattr(self.siteshelper, 'delete_indexer'):
                        self.siteshelper.delete_indexer(domain=domain)
                        removed_count += 1
                        logger.info(f"【{self.plugin_name}】成功移除索引器: {domain}")
                    # 尝试使用remove_indexer方法
                    elif hasattr(self.siteshelper, 'remove_indexer'):
                        self.siteshelper.remove_indexer(domain=domain)
                        removed_count += 1
                        logger.info(f"【{self.plugin_name}】成功移除索引器: {domain}")
                    # 尝试直接修改配置文件
                    else:
                        config_file = "/config/sites.json"
                        if os.path.exists(config_file):
                            try:
                                with open(config_file, 'r', encoding='utf-8') as f:
                                    sites_config = json.load(f)
                                if domain in sites_config:
                                    del sites_config[domain]
                                    with open(config_file, 'w', encoding='utf-8') as f:
                                        json.dump(sites_config, f, ensure_ascii=False, indent=2)
                                    removed_count += 1
                                    logger.info(f"【{self.plugin_name}】通过配置文件移除索引器: {domain}")
                            except Exception as e:
                                logger.error(f"【{self.plugin_name}】修改配置文件失败: {str(e)}")
                except Exception as e:
                    logger.error(f"【{self.plugin_name}】移除索引器失败: {domain} - {str(e)}")
                    
            # 清空已添加索引器列表
            self._added_indexers = []
            logger.info(f"【{self.plugin_name}】共移除了 {removed_count} 个索引器")
            
        except Exception as e:
            logger.error(f"【{self.plugin_name}】移除Prowlarr索引器异常: {str(e)}")

    def _add_prowlarr_indexers(self):
        """
        添加Prowlarr索引器到MoviePilot V2内建索引器
        """
        try:
            # 获取Prowlarr索引器列表
            indexers = self._fetch_prowlarr_indexers()
            if not indexers:
                logger.error(f"【{self.plugin_name}】未获取到Prowlarr索引器")
                return
            
            logger.info(f"【{self.plugin_name}】获取到{len(indexers)}个Prowlarr索引器")
            
            # 先移除已添加的索引器
            self._remove_prowlarr_indexers()
            
            # 等待1秒确保删除操作完成
            time.sleep(1)
            
            # 清空已添加索引器列表
            self._added_indexers = []
            
            # 添加索引器
            for indexer in indexers:
                indexer_id = indexer.get("id")
                if not indexer_id:
                    continue
                    
                if self._indexers and indexer_id not in self._indexers:
                    logger.info(f"【{self.plugin_name}】跳过未选择的索引器: {indexer.get('name')}")
                    continue
                
                domain = f"prowlarr_{indexer_id.lower()}"
                
                # 检查是否已经添加过
                if domain in self._added_indexers:
                    logger.info(f"【{self.plugin_name}】索引器已存在，跳过: {indexer.get('name')}")
                    continue
                
                # 格式化为MoviePilot支持的格式
                mp_indexer = self._format_indexer(indexer)
                if not mp_indexer:
                    continue
                    
                try:
                    # 添加到MoviePilot
                    self.siteshelper.add_indexer(domain=domain, indexer=mp_indexer)
                    self._added_indexers.append(domain)
                    logger.info(f"【{self.plugin_name}】成功添加索引器: {indexer.get('name')}")
                except Exception as e:
                    logger.info(f"【{self.plugin_name}】添加索引器失败: {indexer.get('name')} - {str(e)}")
            
            logger.info(f"【{self.plugin_name}】共添加了{len(self._added_indexers)}个索引器")
                
        except Exception as e:
            logger.error(f"【{self.plugin_name}】添加Prowlarr索引器异常: {str(e)}")
            import traceback
            logger.error(f"【{self.plugin_name}】异常详情: {traceback.format_exc()}")

    def get_indexers(self):
        """
        获取索引器列表
        """
        if not self._host or not self._api_key:
            return {"code": 1, "message": "请先配置Prowlarr地址和API Key"}
        
        try:
            # 获取Prowlarr索引器
            indexers = self._fetch_prowlarr_indexers()
            if not indexers:
                return {"code": 1, "message": "未获取到Prowlarr索引器"}
            
            # 格式化为选项列表
            formatted_indexers = []
            for indexer in indexers:
                formatted_indexers.append({
                    "value": indexer.get("id"),
                    "text": indexer.get("name")
                })
            
            return {"code": 0, "data": formatted_indexers}
                
        except Exception as e:
            logger.error(f"【{self.plugin_name}】获取索引器异常: {str(e)}")
            return {"code": 1, "message": f"获取索引器异常: {str(e)}"}

    def reload_indexers(self):
        """
        重新加载索引器
        """
        if not self._host or not self._api_key:
            return {"code": 1, "message": "请先配置Prowlarr地址和API Key"}
            
        try:
            # 强制启用插件功能
            self._enabled = True
            
            # 重新添加索引器
            self._add_prowlarr_indexers()
            
            return {"code": 0, "message": f"重新加载索引器成功，共添加{len(self._added_indexers)}个索引器"}
                
        except Exception as e:
            logger.error(f"【{self.plugin_name}】重新加载索引器异常: {str(e)}")
            return {"code": 1, "message": f"重新加载索引器失败: {str(e)}"}

    def stop_service(self) -> None:
        """
        停止插件服务
        """
        try:
            logger.info(f"【{self.plugin_name}】正在停止插件服务...")
            # 移除所有添加的索引器
            self._remove_prowlarr_indexers()
            # 清理会话
            self._session = None
            self._cookies = None
            logger.info(f"【{self.plugin_name}】插件服务已停止")
        except Exception as e:
            logger.error(f"【{self.plugin_name}】停止插件服务出错: {str(e)}")

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册定时服务
        """
        return [{
            "id": "Prowlarr_update_indexers",
            "name": "更新Prowlarr索引器",
            "trigger": "interval",
            "func": self._add_prowlarr_indexers,
            "kwargs": {"hours": 12}
        }] 