#!/bin/sh
# Полный прогон в два прохода:
#   1) параллельно (по сценариям) всё, кроме @serial;
#   2) последовательно @serial: эти сценарии меняют общее состояние (правила, календарь) и помешали бы соседям.
# Результаты Allure обоих проходов собираются в $REPORTS_DIR/allure-results.
# Доп. аргументы передаются в оба прохода, например: sh run.sh -t @auth
set -u
REPORTS_DIR="${REPORTS_DIR:-/reports}"
# behavex держит во временной папке отчёта unix-сокет; на смонтированных с Windows дисках
# сокеты не работают, поэтому пишем во внутреннюю папку контейнера и копируем в конце
WORK=/tmp/behavex
ALLURE="-f behavex.outputs.formatters.allure_behavex_formatter:AllureBehaveXFormatter -fo allure-results"

rm -rf "$WORK" "$REPORTS_DIR/ui-failures"   # артефакты UI-падений прошлого прогона

# @demo_failure — сценарий, который падает нарочно (показать артефакты падения в отчёте).
# В обычный прогон не входит; запускается явно: sh run.sh -t @demo_failure
# или вместе со всем набором: INCLUDE_DEMO=1 sh run.sh
# (несколько -t складываются по И, поэтому фильтр просто добавляется к аргументам)
case "${INCLUDE_DEMO:+demo_failure}$*" in
  *demo_failure*) ;;
  *) set -- -t "not @demo_failure" "$@" ;;
esac

behavex -t "not @serial" --parallel-processes "${PARALLEL:-4}" --parallel-scheme scenario \
  -o "$WORK/parallel" $ALLURE "$@"
parallel_rc=$?

behavex -t "@serial" -o "$WORK/serial" $ALLURE "$@"
serial_rc=$?

mkdir -p "$WORK/allure-results"
cp -r "$WORK"/parallel/allure-results/. "$WORK"/serial/allure-results/. "$WORK/allure-results/" 2>/dev/null
# блок Environment на главной странице Allure: где и на чём гоняли
cat > "$WORK/allure-results/environment.properties" <<EOF
Stand=${BASE_URL:-http://gateway}
Config=${TEST_ENV:-docker}
Parallel.processes=${PARALLEL:-4}
Browser=Chromium, Playwright $(python -c "from importlib.metadata import version; print(version('playwright'))")
Python=$(python -c "import platform; print(platform.python_version())")
Commit=${GITHUB_SHA:-local}
EOF

rm -rf "$WORK"/parallel/temp "$WORK"/serial/temp
rm -rf "$REPORTS_DIR/parallel" "$REPORTS_DIR/serial" "$REPORTS_DIR/allure-results"
mkdir -p "$REPORTS_DIR"
cp -r "$WORK"/. "$REPORTS_DIR/"

echo "parallel: rc=$parallel_rc, serial: rc=$serial_rc"
# Опечатка в теге (-t @atuh) даёт пустую выборку, и оба прохода «зелёные» без единого сценария.
# Пустой прогон считаем ошибкой, иначе CI молча пропустит всё.
executed=$(ls "$WORK"/allure-results/*-result.json 2>/dev/null | wc -l)
if [ "$executed" -eq 0 ]; then
  echo "Не выполнено ни одного сценария: проверьте теги и пути в аргументах ($*)"
  exit 3
fi
echo "выполнено сценариев: $executed"
[ "$parallel_rc" -eq 0 ] && [ "$serial_rc" -eq 0 ]
