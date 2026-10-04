"""APScheduler 每日定时刷新：交易日 16:30 自动拉数据并更新信号报告。

可用环境变量 DISABLE_SCHEDULER=1 关闭。
"""
import os

from src import config


def start_scheduler():
    if os.getenv("DISABLE_SCHEDULER"):
        print("scheduler: 已通过 DISABLE_SCHEDULER 关闭")
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from src.report import generate
    from src.data.collector import refresh_all

    def daily_job():
        try:
            refresh_all(verbose=False)
            generate()
            print("scheduler: 每日刷新完成")
        except Exception as e:  # noqa: BLE001
            print("scheduler: 刷新失败", e)

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    sched.add_job(daily_job, "cron", day_of_week="mon-fri",
                  hour=config.REFRESH_CRON_HOUR, minute=config.REFRESH_CRON_MINUTE,
                  id="daily_refresh", replace_existing=True)
    sched.start()
    print(f"scheduler: 已启动（周交易日 {config.REFRESH_CRON_HOUR:02d}:{config.REFRESH_CRON_MINUTE:02d} 自动刷新）")
