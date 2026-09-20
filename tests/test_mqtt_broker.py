"""
Test suite for pure-python MQTT Broker.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import time
import paho.mqtt.client as mqtt
from broker import MQTTBroker

BROKER_PORT = 18883  # test port to avoid conflict

def test_broker_connect_and_pubsub():
    # Run broker in background thread or asyncio loop
    broker = MQTTBroker(host="127.0.0.1", port=BROKER_PORT, storage_path="data/test_retained.json")
    
    loop = asyncio.new_event_loop()
    import threading
    t = threading.Thread(target=lambda: loop.run_until_complete(broker.start()), daemon=True)
    t.start()
    time.sleep(0.5)

    received_messages = []

    def on_message(client, userdata, message):
        received_messages.append((message.topic, message.payload.decode("utf-8"), message.retain))

    # Subscriber 1
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test_sub")
    sub.on_message = on_message
    sub.connect("127.0.0.1", BROKER_PORT, 60)
    sub.subscribe("home/device/+/state")
    sub.loop_start()

    time.sleep(0.3)

    # Publisher
    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test_pub")
    pub.connect("127.0.0.1", BROKER_PORT, 60)
    pub.publish("home/device/light1/state", '{"power":"ON"}', qos=0, retain=True)
    time.sleep(0.5)

    assert len(received_messages) >= 1
    assert received_messages[0][0] == "home/device/light1/state"
    assert '"power":"ON"' in received_messages[0][1]

    # Subscriber 2 connects AFTER publish -> should receive retained message
    retained_msgs = []
    def on_sub2_msg(client, userdata, message):
        retained_msgs.append((message.topic, message.payload.decode("utf-8"), message.retain))

    sub2 = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test_sub2")
    sub2.on_message = on_sub2_msg
    sub2.connect("127.0.0.1", BROKER_PORT, 60)
    sub2.subscribe("home/device/+/state")
    sub2.loop_start()

    time.sleep(0.5)
    assert len(retained_msgs) >= 1
    assert retained_msgs[0][0] == "home/device/light1/state"
    assert retained_msgs[0][2] is True

    sub.loop_stop()
    sub.disconnect()
    pub.disconnect()
    sub2.loop_stop()
    sub2.disconnect()
    print("Broker Pub/Sub and Retain test PASSED!")

if __name__ == "__main__":
    test_broker_connect_and_pubsub()
