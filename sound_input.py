import tuning


class MicrophoneListener
# microphone initialization
# ReSpeaker 4-Mic Array v2.0
self.product_id = parameters['product_id']
self.vendor_id = parameters['vendor_id']
microphone = tuning.find(vid=vendor_id, pid=product_id)