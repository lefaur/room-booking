#!/bin/sh
# Полный прогон: один параллельный проход по сценариям. Сценарии, которые меняют общее состояние
# (@settings, @calendar), идут вместе со всеми под блокировками (framework/locks.py).
#
# Выборка — аргументами behavex или переменными (их заполняет форма ручного запуска в CI):
#   sh run.sh -t @auth
#   TAGS="@booking" EXCLUDE="@ui,@jobs" sh run.sh
#   INCLUDE_DEMO=1 sh run.sh          # вместе с нарочно падающим @demo_failure
# Несколько -t складываются по И; ИЛИ — словом: -t "@auth or @booking" (запятая здесь не работает:
# рядом стоят выражения с not, и behave разбирает всё по новым правилам, где запятая не оператор).
set -u
REPORTS_DIR="${REPORTS_DIR:-/reports}"
# behavex держит во временной папке отчёта unix-сокет; на смонтированных с Windows дисках
# сокеты не работают, поэтому пишем во внутреннюю папку контейнера и копируем в конце
WORK=/tmp/behavex
ALLURE="-f behavex.outputs.formatters.allure_behavex_formatter:AllureBehaveXFormatter -fo allure-results"

rm -rf "$WORK" "$REPORTS_DIR/ui-failures" "$REPORTS_DIR/continue"   # артефакты прошлого прогона

# @demo_failure — сценарий, который падает нарочно (показать артефакты падения в отчёте).
# В обычный прогон не входит; запускается явно (-t @demo_failure, TAGS=@demo_failure) или INCLUDE_DEMO=1
case "${INCLUDE_DEMO:+demo_failure}${TAGS:-}$*" in
  *demo_failure*) ;;
  *) set -- -t "not @demo_failure" "$@" ;;
esac
# @instruction — съёмка скриншотов для инструкций пользователей (docs/user-guide), тоже только явно
# Съёмка идёт по одному: у сценариев общий этаж с одним названием, а кадр не должен ловить чужие брони
case "${TAGS:-}$*" in
  *instruction*) PARALLEL=1 ;;
  *) set -- -t "not @instruction" "$@" ;;
esac
[ -n "${TAGS:-}" ] && set -- -t "$TAGS" "$@"
for tag in $(echo "${EXCLUDE:-}" | tr ',' ' '); do
  set -- -t "not @${tag#@}" "$@"
done

echo "выборка: $*"
behavex --parallel-processes "${PARALLEL:-4}" --parallel-scheme scenario -o "$WORK/run" $ALLURE "$@"
rc=$?

mkdir -p "$WORK/allure-results"
cp -r "$WORK"/run/allure-results/. "$WORK/allure-results/" 2>/dev/null
# блок Environment на главной странице Allure: где и на чём гоняли
cat > "$WORK/allure-results/environment.properties" <<EOF
Stand=${BASE_URL:-http://gateway}
Config=${TEST_ENV:-docker}
Parallel.processes=${PARALLEL:-4}
Prepare.via=${PREPARE_VIA:-sql}
Selection=$*
Browser=Chromium, Playwright $(python -c "from importlib.metadata import version; print(version('playwright'))")
Python=$(python -c "import platform; print(platform.python_version())")
Commit=${GITHUB_SHA:-local}
EOF

rm -rf "$WORK"/run/temp
rm -rf "$REPORTS_DIR/run" "$REPORTS_DIR/parallel" "$REPORTS_DIR/serial" "$REPORTS_DIR/allure-results"
mkdir -p "$REPORTS_DIR"
cp -r "$WORK"/. "$REPORTS_DIR/"

echo "behavex: rc=$rc"
# Опечатка в теге (-t @atuh) даёт пустую выборку, и прогон «зелёный» без единого сценария.
# Пустой прогон считаем ошибкой, иначе CI молча пропустит всё.
executed=$(ls "$WORK"/allure-results/*-result.json 2>/dev/null | wc -l)
if [ "$executed" -eq 0 ]; then
  echo "Не выполнено ни одного сценария: проверьте теги и пути в выборке ($*)"
  exit 3
fi
echo "выполнено сценариев: $executed"
exit "$rc"
