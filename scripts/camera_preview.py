import cv2

# camera = cv2.VideoCapture(0)
#
# while True:
#     ret, frame = camera.read()
#     if not ret:
#         continue

if __name__ == '__main__':
    capture = cv2.VideoCapture(0)
    if capture.isOpened():
        print('Opened camera successfully')
    else:
        print('Error: could not open camera')
    while True:
        success, img = capture.read()
        if not success:
            print('Error: could not read current frame')
        img = cv2.resize(img, (640, 480))
        cv2.imshow("img", img)
        action = cv2.waitKey(10) & 0xff
        if action == 27:
            break
    cv2.destroyAllWindows()
