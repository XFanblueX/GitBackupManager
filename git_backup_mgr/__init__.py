import time
from typing import Any

from mcdreforged.api.all import *
from git import Repo, InvalidGitRepositoryError, GitCommandError
from git_backup_mgr.config import Configure


repo: Repo
git: Repo.git
remote: Repo.remote
config: Configure
CONFIG_FILE_NAME: str = "GitBackupManager.json"
game_saved: bool = False
plugin_unloaded: bool = False
restore_version = None
restore_comment = None
abort_restore: bool = True
timer = None


class Events:
    backup_done = LiteralEvent("git_backup_mgr.backup_done")
    backup_trig = LiteralEvent("git_backup_mgr.backup_trig")
    restore_done = LiteralEvent("git_backup_mgr.restore_done")
    restore_trig = LiteralEvent("git_backup_mgr.restore_trig")


def click_run_cmd(msg: Any, tip: Any, cmd: str) -> RTextBase:
    proceed_msg = msg.copy() if isinstance(msg, RTextBase) else RText(msg)
    return proceed_msg.set_hover_text(tip).set_click_event(RAction.run_command, cmd)


def load_config(server: PluginServerInterface):
    global config
    config = server.load_config_simple(file_name=CONFIG_FILE_NAME, target_class=Configure)


def print_msg(source: CommandSource, msg, prefix='[GBM]'):
    msg = RTextList(prefix, msg)
    if source.is_player:
        source.get_server().say(msg)
    else:
        source.reply(msg)


def broadcast_msg(server: ServerInterface, msg, prefix='[GBM]'):
    msg = RTextList(prefix, msg)
    if server.is_server_startup():
        server.broadcast(msg)
    else:
        server.logger.info(msg)


def git_init() -> None:
    """
    当不存在.git路径时自动init
    :return:None
    """
    global repo
    try:
        repo = Repo(Configure.server_path)
    except InvalidGitRepositoryError:
        print("[GBM]正在初始化.git文件夹...")
        repo = Repo.init(Configure.server_path)
        print("[GBM]初始化完成")
    global git
    git = repo.git
    git.config("user.name", f'"{config.user_name}"')
    git.config("user.email", f'"{config.user_email}"')
    if config.remote_backup:
        git.remote('add', 'origin', config.remote_origin)
        global remote
        remote = repo.remote()
    with open((config.server_path + '/.gitignore'), 'w+') as f:
        for i in config.saves:
            for j in config.ignored_files:
                f.write(f"{i}/{j}\n")


@new_thread("GBM Backup Thread")
def create_backup(source: CommandSource, comment='无') -> None:
    try:
        print_msg(source, "正在备份...")
        start_time = time.time()

        # 备份开始
        source.get_server().execute("save-off")
        source.get_server().execute("save-all flush")
        while True:
            time.sleep(0.01)
            if game_saved:
                break
            if plugin_unloaded:
                print_msg(source, "插件被卸载,备份取消")
                return
        time.sleep(0.01)
        for worlds in config.saves:
            git.add(worlds)
        backup_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        comment = f"{backup_time} 备注:{comment}"
        git.commit('-m', comment)
        end_time = time.time()
        time_difference = round(end_time - start_time, 1)
        print_msg(source, f"备份完成! 耗时{time_difference}秒")
        if config.remote_backup:
            print_msg(source, "正在上传...")
            git.push('master')
            print_msg(source, "上传完成!")
    except Exception as e:
        print_msg(source, f"发生错误!错误为:\n{e}")
    else:
        pass  # 此处应发出事件Events.backup_done WIP
    finally:
        source.get_server().execute("save-on")


def restore_backup(source: CommandSource, version="HEAD^"):
    global abort_restore
    abort_restore = False
    try:
        if version == "HEAD^":
            version = git.log("-1", '--pretty=format:%h')
            comment = git.log("-1", '--pretty=format:%s')
        else:
            comment = git.log("-1", "--pretty=format:%s", version)
    except GitCommandError:
        print_msg(source, "§c发生错误!请检查指定版本是否存在!")
        return
    global restore_version, restore_comment
    restore_version = version
    restore_comment = comment
    print_msg(source, f"正在回退至§2{version}§r版本:[{comment}]")
    print_msg(source,
              click_run_cmd("使用!!gb confirm确认", "点击确认", "!!gb confirm")
              + ','
              + click_run_cmd("使用!!gb abort取消", "点击取消", "!!gb abort "))


@new_thread("GBM Restore Thread")
def _restore_backup(source, ver, com):
    print_msg(source, f"10秒后关闭服务器并回退至版本{ver}!")
    for cd in range(10):
        print_msg(source,
                  f"距离回退至{ver}还有{10 - cd}秒,版本信息:[{com}]"
                  + ','
                  + click_run_cmd("使用!!gb abort取消", "取消回退!", "!!gb abort")
                  )
        for i in range(10):
            time.sleep(0.1)
            if abort_restore:
                print_msg(source, "回退取消!")
                return
    print_msg(source, f"[DEBUG]{ver}[{com}]")


def _confirm_restore(source: CommandSource):
    global restore_version, restore_comment
    if restore_version is None:
        print_msg(source, "没有操作需要确认!")
    else:
        version = restore_version
        comment = restore_comment
        restore_version = None
        restore_comment = None
        _restore_backup(source, version, comment)


def _abort_restore(source: CommandSource):
    global restore_version, restore_comment, abort_restore
    restore_version = None
    restore_comment = None
    abort_restore = True


"""此自动备份函数已弃用,新自动备份参见timer.py"""


# def auto_create_backup(custom_time=0, default_time=1800, state=True) -> None:
#     """git add and git commit"""
#     create_backup()
#     if custom_time == 0:
#         sleep(default_time)
#     else:
#         sleep(custom_time)
#     auto_create_backup()
#
#
# def timer(time: int) -> None:
#     """
#     当执行这个函数时，该线程暂停time秒
#     :param time:
#     :return: None
#     """
#     sleep(time)


def register_command(server: PluginServerInterface) -> None:
    """
    实现以下命令:
    !!gb-init
        -make [comment: str]
        -back [id: str]
        -confirm
        -about
        -list
        -remote
            -enable
            -disable
            -address [address: str]
    :return:None
    """
    server.register_command(
        Literal("!!gb").
        then(
            Literal("init").runs(git_init)
        ).
        then(
            Literal("make").runs(lambda src: create_backup(src)).
            then(
                GreedyText("comment").runs(lambda src, ctx: create_backup(src, ctx["comment"]))
            )
        ).
        then(
            Literal("back").runs(lambda src: restore_backup(src)).
            then(
                Text("version").runs(lambda src, ctx: restore_backup(src, ctx["version"]))
            )
        ).
        then(
            Literal("confirm").runs(lambda src: _confirm_restore(src))
        ).
        then(
            Literal("abort").runs(lambda src: _abort_restore(src))
        ).
        then(
            Literal("list")
        ).
        then(
            Literal("remote").
            then(
                Literal("enable")
            ).
            then(
                Literal("disable")
            ).
            then(
                Literal("address").
                then(
                    QuotableText("address")
                )
            )
        ).
        then(
            Literal("timer").
            then(
                Literal("enable")
            ).
            then(
                Literal("disable")
            ).
            then(
                Literal("overlay").
                then(Integer("overlay"))
            )
        )
    )


def on_info(server: PluginServerInterface, info: Info):
    if not info.is_user:
        if info.content in config.saved_world_keywords:
            global game_saved
            game_saved = True


def on_load(server: ServerInterface, prev):
    from git_backup_mgr.timer import TimedBackup
    load_config(server.as_plugin_server_interface())
    git_init()
    register_command(server.as_plugin_server_interface())
    global timer
    timer = TimedBackup(server.as_plugin_server_interface())
    try:
        timer.time_last_backup = prev.timer.time_last_backup
    except (AttributeError, ValueError):
        pass
    timer.set_enabled(config.timed_backup)
    timer.start()


def on_unload(server: ServerInterface):
    global plugin_unloaded
    plugin_unloaded = True
