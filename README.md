
# ptaf_backuper
Скрипт для автоматического создания бэкапов по расписанию, а так же их ротации согласно заданному времени жизни (backup_ttl). Который может быть запущен как на самом сервере ptaf так и на узле, у которого есть сетевая доступность до адреса веб-интерфейса  ptaf'а \
Продолжает работать после рестарта узла \
В резервной копии сохраняются параметры:

 - учетных записей и пользовательских ролей;
 - веб-приложений и шаблонов политик безопасности;
 - наборов системных и пользовательских правил;
 - действий;
 - глобальных списков;
 - профилей трафика, защищаемых серверов и IP-адресов для прослушивания;
 - действий с HTTP-заголовками;
 - конфигураций SSL и цепочек сертификатов SSL, включая закрытые ключи. \
В резервной копии не сохраняются данные о событиях безопасности.

# Инструкция по использованию

1. Заполняем файл data.json
     - Айпи адрес веб-интерфейса(ptaf_ip)
     - Логин и Пароль УЗ с правами на создания бэкапов(ptaf_login & ptaf_password)
     - Время жизни бэкапов(backup_ttl)
     - Периодичность создания бэкапов(backup_frequency)
     - Папка в которой будут дополнительно храниться бэкапы(path_to_save_backups)
 backup_ttl и backup_frequency поддерживают следующие форматы: \
              m - минуты \
              h - часы \
              d - дни \
              w - недели \
        Применяются по отдельности(Нельзя указать 1d2h), правильно будет 26h
   - **`backup_schedule`** – (в приоритете) точное расписание в формате systemd calendar. (При указании вместе с backup_frequency будет выбран backup_schedule) \
  Примеры: \
  - `"*-*-* 02:00:00"` – каждый день в 2:00 \
  - `"Mon..Fri 09:00:00"` – по будням в 9:00 \
  - `"Sun 03:00:00"` – каждое воскресенье в 3:00 \

 2. Заходим на сервер и скачиваем туда файлы скрипта
 3. Заходим под root'a
 4. Устанавливаем зависимости \
      sudo apt-get update \
      sudo apt-get install python3 python3-venv python3-pip     
 5. Выполняем следующие команды: \
      cp -r backup_manager /opt && \\ \
      cd /opt/backup_manager && \\ \
      chmod 600 data.json && \\ \
      chmod 700 start.sh setup_systemd.sh && \\ \
      chmod 644 backuper.py requirements.txt && \\ \
      chmod +x start.sh setup_systemd.sh 
  6. Производим тестовый запуск скрипта \
      sudo ./start.sh \
  7. Если все успешно выполнилось устанавливаем таймер на запуск скрипта \
      sudo ./setup_systemd.sh

  8. Если нужно сменить периодичность и срок хранения бэкапов меняем значения в файле data.json и перезапускаем sudo ./setup_systemd.sh

# Команды для отладки

  1. Просмотр логов выполнения скрипта \
       tail -f /opt/ptaf_backuper/backup.log или cat /opt/ptaf_backuper/backup.log
  2. Проверка логов на ошибки \
       grep ERROR /opt/ptaf_backuper/backup.log
  3. Проверка прав доступа \
       ls -la /opt/ptaf_backuper/
  4. Просмотр логов systemd \
       sudo journalctl -u ptaf_backuper.service -f \
       sudo systemctl status ptaf_backuper.service \
       sudo systemctl status ptaf_backuper.timer
  5. Ручная остановка и запуск сервиса \
       sudo systemctl stop ptaf_backuper.timer \
       sudo systemctl start ptaf_backuper.service
