from models.game_state import GameState
from data.traits import TRAITS
from models.disease import Disease

class test_models:
    def test_world_creation():
        game = GameState()
        assert len(game.countries) > 50
        assert "USA" in game.countries
        assert "India" in game.countries

    def test_country_health():
        game = GameState()
        usa = game.countries["USA"]
        usa.infected = 1000
        assert (
            usa.healthy
            ==
            usa.population - 1000
        )
    
    def test_trait_evolution():
        disease = Disease()
        disease.evolve(
            "Air1",
            TRAITS["Air1"]
        )
        assert disease.air_transmission == 1
        assert disease.infectivity > 1.0

