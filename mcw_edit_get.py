import json
import logging
import os
import threading
from copy import deepcopy
from functools import reduce
from time import strftime, localtime, sleep

import openpyxl as xl
import pywikiapi as wiki

__author__ = "QWERTY770"
__version__ = "3.0"
# 2023/11/09: MCW moved to https://zh.minecraft.wiki
# 2024/01/06: Version 2.0, added multi-revision query to reduce the number of requests
# 2024/03/23: Version 3.0, added pywikiapi

# variables
total_edits = 880800
threads = 16
per_thread = int(total_edits / 50 / threads)
total_slices = int(total_edits / 5000)

folder = os.getcwd()
logger = logging.getLogger('MCW EditCount Script')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler('editcount-script-v2.log', encoding="utf-8")
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(ch)

site = wiki.Site("https://zh.minecraft.wiki/api.php")
# revisions api
rev_api = "https://zh.minecraft.wiki/api.php?action=query&format=json&prop=revisions&revids="
namespace_names = {0: "（主）", 1: "讨论", 2: "用户", 3: "用户讨论",
                   4: "Minecraft Wiki", 5: "Minecraft Wiki讨论",
                   6: "文件", 7: "文件讨论", 8: "MediaWiki", 9: "MediaWiki讨论",
                   10: "模板", 11: "模板讨论", 12: "帮助", 13: "帮助讨论",
                   14: "分类", 15: "分类讨论", 828: "模块", 829: "模块讨论",
                   2300: "Gadget", 2301: "Gadget talk", 2302: "Gadget definition", 2303: "Gadget definition talk",
                   9996: "地下城教程", 9997: "地下城教程讨论", 9998: "教程", 9999: "教程讨论",
                   10000: "地下城", 10001: "地下城讨论", 10002: "地球", 10003: "地球讨论",
                   10004: "故事模式", 10005: "故事模式讨论", 10006: "传奇", 10007: "传奇讨论"}
#                    302: "Property", 303: "Property talk", 308: "Concept", 309: "Concept talk",
#                    312: "smw/schema", 313: "smw/schema talk", 314: "Rule", 315: "Rule talk"
namespace_names_keys = namespace_names.keys()
namespace_order = dict([(j, i) for i, j in enumerate(sorted(namespace_names.keys()))])

if os.path.exists(os.path.join(folder, "config.json")):
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)  # type: dict
        headers = config["headers"] if "headers" in config else {}
        username = config["username"] if "username" in config else None
        password = config["password"] if "password" in config else None


def get_revs(start: int, end: int) -> None:
    logger.debug(f"{start} to {end} started!")
    for i in range(start // 50, end // 50):
        try:
            data = site("query", prop="revisions", EXTRAS={"headers": headers},
                        revids="|".join([str(rev) for rev in range(i * 50 + 1, i * 50 + 51)]))
            with open(os.path.join(folder, "rev", f"rev_{i}.txt"), "w", encoding="utf-8") as f:
                f.write(str(data))
        except wiki.utils.ApiError as err:
            logger.error(err)
            sleep(10)
            get_revs(i * 50 + 1, end)
    if end % 50 != 0:
        try:
            data = site("query", prop="revisions", EXTRAS={"headers": headers},
                        revids="|".join([str(rev) for rev in range((end // 50) * 50 + 1, end + 1)]))
            with open(os.path.join(folder, "rev", f"rev_{(end // 50)}.txt"), "w", encoding="utf-8") as f:
                f.write(str(data))
        except wiki.utils.ApiError as err:
            logger.error(err)
            sleep(10)
            get_revs((end // 50) * 50 + 1, end)
    logger.debug(f"{start} to {end} finished!")


def get_edit_dic(start: int, end: int) -> dict:
    if start > end:
        return {}
    user_dic = {}
    for i in range(start // 50, end // 50):
        pth = os.path.join(folder, "rev", f"rev_{i}.txt")
        if not os.path.exists(pth):
            get_revs(i, i)
        with open(pth, "r", encoding="utf-8") as f:
            js = eval(f.read())
        if "pages" not in js["query"]:
            continue
        pages = js["query"]["pages"]
        for p in pages:
            namespace = p["ns"]
            revs = p["revisions"]
            for rev in revs:
                try:
                    revid = rev["revid"]
                    if revid > end or revid < start:
                        continue
                    if "user" not in rev and "userhidden" in rev:
                        user = "<HIDDEN_USER>"
                        logger.debug(f"The user is hidden in revision {revid}")
                    else:
                        user = rev["user"]
                    if user not in user_dic:
                        user_dic[user] = {"all": 0}
                    if namespace not in user_dic[user]:
                        user_dic[user][namespace] = 1
                    else:
                        user_dic[user][namespace] += 1
                    user_dic[user]["all"] += 1
                except Exception as err:
                    logger.error(str(err))
                    logger.error(f"JSON={str(js)}")
                    continue
    return user_dic


def merge_edit_dic(dic1: dict, dic2: dict) -> dict:
    result = deepcopy(dic1)
    for username in dic1.keys():
        for namespace in dic1[username].keys():
            if username in dic2:
                if namespace in dic2[username]:
                    result[username][namespace] += dic2[username][namespace]
    del username, namespace
    for username in dic2.keys():
        for namespace in dic2[username].keys():
            if username not in result:
                result[username] = dic2[username]
            else:
                if namespace not in result[username]:
                    result[username][namespace] = dic2[username][namespace]
    return result


def make_workbook(dic: dict, filename=None) -> None:
    if filename is None:
        filename = f"minecraftwiki-useredit-{strftime('%Y%m%d-%H%M%S', localtime())}.xlsx"
    wb = xl.Workbook()
    ws = wb.create_sheet('main', 0)
    ws.cell(row=1, column=1).value = "用户名"
    ws.cell(row=1, column=2).value = "编辑总计"
    for a, b in enumerate(namespace_names.keys()):
        ws.cell(row=1, column=a + 3).value = namespace_names[b]

    for m, i in enumerate(dic.keys()):
        user = dic[i]
        ws.cell(row=m + 2, column=1).value = i
        ws.cell(row=m + 2, column=2).value = user["all"]
        for j in namespace_names_keys:
            if j in user:
                ws.cell(row=m + 2, column=namespace_order[j] + 3).value = user[j]
            else:
                ws.cell(row=m + 2, column=namespace_order[j] + 3).value = 0

    wb.save(os.path.join(folder, filename))
    wb.close()
    logger.info("Successfully generated workbook sheet(s)!")


def download_data() -> None:
    if username is not None and password is not None:
        site.login(username, password)
    thread_list = []
    for i in range(threads):
        t = threading.Thread(target=get_revs, args=(1 + per_thread * 50 * i, per_thread * 50 * (i + 1)))
        t.start()
        thread_list.append(t)
    for i in thread_list:
        i.join()
    get_revs(per_thread * 1600 + 1, total_edits)


def workbook() -> None:
    for i in range(total_slices):
        slic = str(get_edit_dic(1 + 5000 * i, 5000 + 5000 * i))
        with open(os.path.join(folder, "slices", f"{i}.txt"), "w", encoding="utf-8") as f:
            f.write(slic)
    logger.info(f"Successfully generated {total_slices} slices!")

    slices_list = []
    for i in range(total_slices):
        with open(os.path.join(folder, "slices", f"{i}.txt"), "r", encoding="utf-8") as f:
            slices_list.append(eval(f.read()))
    make_workbook(merge_edit_dic(reduce(merge_edit_dic, slices_list), get_edit_dic(total_slices * 5000, total_edits)))


if __name__ == "__main__":
    # download_data()
    # workbook()
    logger.info("Finished!")
