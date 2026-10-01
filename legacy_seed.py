# -*- coding: utf-8 -*-
"""One-time/idempotent legacy seed copied from the latest local Fantasy Dawair package."""
import server

GROUPS = {
    1: ['راكان محمد التجلي','داود احمد العثمان','مصعب عيسى الرشيدي','عيسى محمد الهزيم','فيصل موسى المطيري','علي عبدالوهاب الخلفي','عثمان خالد العثمان'],
    2: ['محمد مشعل العنزي','عبدالمحسن محمد القائم','حمد محمد الأنصاري','سعد نايف المقبول','محمد عبدالمجيد الفيلكاوي','احمد علي الدهام'],
    3: ['أنس عبدالعزيز الحجّي','رشود محمد الشمري','محمد ثامر العجمي','ناصر ثامر العجمي','تركي محمد الدوسري','حمد أحمد الماجد','أحمد عبدالمجيد الفيلكاوي'],
    4: ['سالم فهد الأحمد','عبدالله محمد شمس الدين','عبدالله إبراهيم الناشي','علي عبدالوهاب العيسى','راشد صلاح البشير','محمد مدحت محمود','معاذ أنس الشايجي'],
}

LEGACY_SETTINGS = {
    'group_count':'4',
    'players_per_group':'2',
    'squad_size':'8',
    'starters':'6',
    'bench':'2',
    'chips_once':'1',
}

def seed():
    with server.LOCK:
        for k,v in LEGACY_SETTINGS.items():
            server.execq(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",
                (k,v),
            )

        if server.val("SELECT COUNT(*) FROM players") == 0:
            for group_no,names in GROUPS.items():
                for name in names:
                    server.insert_id(
                        "INSERT INTO players(name,group_no,active,created_at) VALUES(?,?,1,?)",
                        (name,group_no,server.now()),
                    )

        if server.val("SELECT COUNT(*) FROM participants") == 0:
            code='DEMO'
            server.insert_id(
                "INSERT INTO participants(name,code_hash,code_hint,active,created_at) VALUES(?,?,?,1,?)",
                ('مشترك تجريبي',server.h(code,'dawair-participant-v1'),code[-3:],server.now()),
            )

        if not server.PG:
            server.conn.commit()

    print("Legacy seed complete:",
          "players=", server.val("SELECT COUNT(*) FROM players"),
          "participants=", server.val("SELECT COUNT(*) FROM participants"),
          "rounds=", server.val("SELECT COUNT(*) FROM rounds"))

if __name__ == "__main__":
    seed()
