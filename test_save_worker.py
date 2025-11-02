from bot import save_worker_to_db

state = {
    "name": "Test Teacher",
    "phone": "0912345678",
    "work_type": "الخدمات التعليمية",
    "edu_type": "تمهيدي",
    "location": (32.0, 44.0)
}
uid = 999999
code = save_worker_to_db(uid, state)
print('worker_code:', code)
