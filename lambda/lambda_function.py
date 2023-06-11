import random
import logging
import os
import boto3

from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_core.handler_input import HandlerInput

from ask_sdk_model import Response
from ask_sdk_dynamodb.adapter import DynamoDbAdapter

from utils import get_random_state, check_closeness

ddb_region = os.environ.get('DYNAMODB_PERSISTENCE_REGION')
ddb_table_name = os.environ.get('DYNAMODB_PERSISTENCE_TABLE_NAME')
ddb_resource = boto3.resource('dynamodb', region_name=ddb_region)
dynamodb_adapter = DynamoDbAdapter(table_name=ddb_table_name, create_table=False, dynamodb_resource=ddb_resource)
sb = CustomSkillBuilder(persistence_adapter=dynamodb_adapter)
MAX_GUESSES = 8

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@sb.request_handler(can_handle_func=is_request_type('LaunchRequest'))
def launch_request_handler(handler_input):
    attr = handler_input.attributes_manager.persistent_attributes
    if not attr:
        attr['games_played'] = 0
        attr['games_won'] = 0
        attr['playing'] = False

    handler_input.attributes_manager.session_attributes = attr

    speech_text = f'You have won {attr["games_won"]} out of {attr["games_played"]} games. Would you like to {"continue your game" if attr["playing"] else "play a new game"}?'
    reprompt = 'Say yes to begin or no to quit.'

    handler_input.response_builder.speak(speech_text).ask(reprompt)
    return handler_input.response_builder.response


@sb.request_handler(can_handle_func=is_intent_name('AMAZON.HelpIntent'))
def help_intent_handler(handler_input):
    speech_text = f'A random U.S. state is chosen and you have {MAX_GUESSES} attempts to guess it.'
    reprompt = 'Try guessing a U.S. state.'

    handler_input.response_builder.speak(speech_text).ask(reprompt)
    return handler_input.response_builder.response


@sb.request_handler(
    can_handle_func=lambda input:
        is_intent_name('AMAZON.CancelIntent')(input) or
        is_intent_name('AMAZON.StopIntent')(input))
def cancel_and_stop_intent_handler(handler_input):
    speech_text = 'Thanks for playing.'

    handler_input.response_builder.speak(speech_text).set_should_end_session(True)
    return handler_input.response_builder.response


@sb.request_handler(can_handle_func=is_request_type('SessionEndedRequest'))
def session_ended_request_handler(handler_input):
    logger.info(f'Session ended with reason: {handler_input.request_envelope.request.reason}')
    return handler_input.response_builder.response


def currently_playing(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    return session_attr.get('playing','')


@sb.request_handler(can_handle_func=lambda input:
                    is_intent_name('AMAZON.YesIntent')(input))
def yes_handler(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    session_attr['target_state'] = session_attr['target_state'] if session_attr['playing'] else get_random_state()
    session_attr['playing'] = True
    session_attr['guesses'] = session_attr.get('guesses', 0)

    speech_text = f'Guess a U.S. state. You have {MAX_GUESSES-session_attr["guesses"]} {"guesses" if MAX_GUESSES-session_attr["guesses"] != 1 else "guess"} left.'
    reprompt = 'Try saying a U.S. state.'

    handler_input.response_builder.speak(speech_text).ask(reprompt)
    return handler_input.response_builder.response


@sb.request_handler(can_handle_func=lambda input:
                    not currently_playing(input) and
                    is_intent_name('AMAZON.NoIntent')(input))
def no_handler(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes

    handler_input.attributes_manager.persistent_attributes = session_attr
    handler_input.attributes_manager.save_persistent_attributes()

    speech_text = 'Ok. Have a great day.'

    handler_input.response_builder.speak(speech_text)
    return handler_input.response_builder.response


@sb.request_handler(can_handle_func=lambda input:
                    currently_playing(input) and
                    is_intent_name('StateGuessIntent')(input))
def number_guess_handler(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    target_state = session_attr['target_state']
    guess_state = handler_input.request_envelope.request.intent.slots['state'].value.lower()

    session_attr['guesses'] += 1

    reprompt = 'Say yes to start a new game or no to exit.'
    if guess_state == target_state or session_attr['guesses'] >= MAX_GUESSES:
        if guess_state == target_state:
            speech_text = f'Congrats. {target_state.title()} is correct. You got it in {session_attr["guesses"]} {"guesses" if session_attr["guesses"] != 1 else "guess"}. Would you like to play a new game?'
            session_attr['games_won'] += 1
        else:
            speech_text = f'{check_closeness(target_state,guess_state)}. You\'ve run out of guesses. {target_state.title()} was the state. Would you like to play a new game?'

        session_attr['games_played'] += 1
        session_attr['playing'] = False
        session_attr['guesses'] = 0
    else:
        speech_text = f'{check_closeness(target_state,guess_state)}. {"Guess again" if MAX_GUESSES-session_attr["guesses"]!=1 else "You have one last guess"}.'
        reprompt = 'Please guess a U.S. state.'
    
    handler_input.attributes_manager.persistent_attributes = session_attr
    handler_input.attributes_manager.save_persistent_attributes()

    handler_input.response_builder.speak(speech_text).ask(reprompt)
    return handler_input.response_builder.response


@sb.request_handler(can_handle_func=lambda input:
                    is_intent_name('AMAZON.FallbackIntent')(input) or
                    is_intent_name('AMAZON.YesIntent')(input) or
                    is_intent_name('AMAZON.NoIntent')(input))
def fallback_handler(handler_input):
    session_attr = handler_input.attributes_manager.session_attributes
    speech_text = 'I have absolutely no idea what you are talking about.'
    reprompt = 'Please guess a U.S. state.' if session_attr.get('playing', False) else 'Say yes to start the game or no to quit.'
    handler_input.response_builder.speak(speech_text).ask(reprompt)
    return handler_input.response_builder.response


@sb.request_handler(can_handle_func=lambda input: True)
def unhandled_intent_handler(handler_input):
    speech_text = 'Say yes to continue or no to end the game.'
    handler_input.response_builder.speak(speech_text).ask(speech_text)
    return handler_input.response_builder.response


@sb.exception_handler(can_handle_func=lambda i, e: True)
def all_exception_handler(handler_input, exception):
    logger.error(exception, exc_info=True)
    speech_text = 'Sorry, I didn\'t get that. Could you say that again?'
    handler_input.response_builder.speak(speech_text).ask(speech_text)
    return handler_input.response_builder.response


@sb.global_response_interceptor()
def log_response(handler_input, response):
    logger.info(f'Response: {response}')


lambda_handler = sb.lambda_handler()
