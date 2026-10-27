from nimea_robot.brain import Frases


def test_corta_por_frases_al_vuelo():
    dichas = []
    f = Frases(dichas.append)
    for trozo in ["Hola, Car", "men. ¡Qué ", "alegría oírte! Va", "ya. ¿Cómo has dormido", "? Bien"]:
        f.alimentar(trozo)
    # La última frase se queda esperando por si sigue llegando texto.
    assert dichas == ["Hola, Carmen.", "¡Qué alegría oírte!", "Vaya. ¿Cómo has dormido?"]
    f.cerrar()
    assert dichas[-1] == "Bien"
