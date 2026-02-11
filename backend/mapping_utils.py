# backend/mapping_utils.py (파일 내용을 반영한 버전)

def map_google_to_yelp_style(place_data):
    parking = place_data.get('parkingOptions') or {}
    accessibility = place_data.get('accessibilityOptions') or {}
    
    # helper: 데이터 부재(-1), 없음(0), 있음(1) 처리
    def check_val(val):
        if val is True: return 1
        if val is False: return 0
        return -1

    return {
        # 1. 파일에 명시된 주차 세부 옵션 반영 
        "BusinessParking": 1 if any([parking.get('freeParkingLot'), parking.get('valetParking'), parking.get('paidParkingLot')]) 
        else (-1 if not parking else 0),
        
        # 2. 접근성 (휠체어 접근성 등) 
        "WheelchairAccessible": check_val(accessibility.get('wheelchairAccessibleSeating')),
        
        # 3. 단체 적합성 및 어린이 메뉴 (GoodForKids 심화) 
        "RestaurantsGoodForGroups": check_val(place_data.get('goodForGroups')),
        "GoodForKids": check_val(place_data.get('menuForChildren')),
        
        # 4. 주류 및 매장 특성 
        "Alcohol": "full_bar" if (place_data.get('servesCocktails') or place_data.get('servesWine')) else "none",
        "DineIn": check_val(place_data.get('dineIn')),
        "OutdoorSeating": check_val(place_data.get('outdoorSeating')),
        
        # 5. 가격대 및 기타 [cite: 16, 25]
        "RestaurantsPriceRange2": place_data.get('priceLevel', 0),
        "Vegetarian": check_val(place_data.get('servesVegetarianFood'))
    }