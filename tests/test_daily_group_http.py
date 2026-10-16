import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from vocabulary.http_app import create_server


class DailyGroupHttpTests(unittest.TestCase):
    def test_group_crud_assignment_and_invalid_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            server=create_server('127.0.0.1',0,root/'test.db',root,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            def request(method,path,payload=None):
                body=json.dumps(payload).encode() if payload is not None else None
                with urlopen(Request(f'http://127.0.0.1:{server.server_port}'+path,data=body,method=method,headers={'Content-Type':'application/json'})) as response:
                    return response.status,json.load(response)
            try:
                status,group=request('POST','/api/daily-groups',{'name':'水果'})
                self.assertEqual(status,201)
                _,item=request('POST','/api/daily-expressions',dict(phrase='pomelo',meaning='柚子',category='词汇',group_id=str(group['id'])))
                self.assertEqual(item['group_id'],group['id'])
                _,listing=request('GET','/api/daily-groups')
                self.assertEqual(listing['items'][0]['item_count'],1)
                _,renamed=request('PUT',f'/api/daily-groups/{group["id"]}',{'name':'水果合集'})
                self.assertEqual(renamed['name'],'水果合集')
                for method,path,payload,code in [('POST','/api/daily-groups',{'name':'水果合集'},400),('PUT','/api/daily-groups/99999',{'name':'missing'},404),('DELETE','/api/daily-groups/99999',None,404),('POST','/api/daily-expressions',dict(phrase='x',meaning='测试',category='词汇',group_id=99999),400)]:
                    with self.subTest(path=path),self.assertRaises(HTTPError) as error:
                        request(method,path,payload)
                    self.assertEqual(error.exception.code,code)
                    error.exception.close()
                request('DELETE',f'/api/daily-groups/{group["id"]}')
                self.assertIsNone(request('GET',f'/api/daily-expressions/{item["id"]}')[1]['group_id'])
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
