from behave import step

from framework.support import expect


@step("ответ {status:d}")
def step_status(context, status):
    expect(context.resp, status)


@step('ответ {status:d} с сообщением "{text}"')
def step_status_with_message(context, status, text):
    expect(context.resp, status, contains=text)
