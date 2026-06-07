class Car:
    def __init__(self, brand: str, model: str, year: int, registration: str):
        self.brand = brand
        self.model = model
        self.year = year
        self.registration = registration
        self.availability = True

    def display_details(self):
        status = "Available" if self.availability else "Rented"
        print(
            f"[{self.registration}] {self.year} {self.brand} {self.model} - Status: {status}")

    def is_available(self) -> bool:
        return self.availability


class Agency:
    def __init__(self):
        self.cars = []

    def add_car(self, car: Car):
        self.cars.append(car)
        print(f"\n Success: {car.brand} {car.model} added to fleet.")

    def rent_car(self, registration: str):
        for car in self.cars:
            if car.registration.upper() == registration.upper():
                if car.is_available():
                    car.availability = False
                    print(
                        f"\n Success: Car {registration.upper()} has been rented.")
                    return
                else:
                    print(
                        f"\n Error: Car {registration.upper()} is already rented.")
                    return
        print(f"\n Error: Registration {registration.upper()} not found.")

    def return_car(self, registration: str):
        for car in self.cars:
            if car.registration.upper() == registration.upper():
                if not car.is_available():
                    car.availability = True
                    print(
                        f"\n Success: Car {registration.upper()} is now available again.")
                    return
                else:
                    print(
                        f"\n Notice: Car {registration.upper()} was already available.")
                    return
        print(f"\n Error: Registration {registration.upper()} not found.")

    def display_available_cars(self):
        print("\n=== AVAILABLE CARS ===")
        available_cars = [car for car in self.cars if car.is_available()]
        if not available_cars:
            print("No cars are currently available in the fleet.")
        else:
            for car in available_cars:
                car.display_details()
        print("======================\n")


# Interactive Menu Logic
def main():
    agency = Agency()

    # Pre-populating with 2 cars so the system isn't empty at start
    agency.add_car(Car("Toyota", "Corolla", 2021, "ABC-123"))
    agency.add_car(Car("Ford", "Explorer", 2022, "XYZ-789"))

    while True:
        print("\n--- CAR RENTAL MANAGEMENT SYSTEM ---")
        print("1. Add a car to the fleet")
        print("2. Rent a car")
        print("3. Return a car")
        print("4. Display available cars")
        print("5. Exit")

        choice = input("Select an option (1-5): ").strip()

        if choice == "1":
            print("\n--- Add New Car ---")
            brand = input("Enter brand: ")
            model = input("Enter model: ")
            try:
                year = int(input("Enter year: "))
            except ValueError:
                print("Invalid year. Setting to 2026.")
                year = 2026
            registration = input("Enter registration code: ")

            new_car = Car(brand, model, year, registration)
            agency.add_car(new_car)

        elif choice == "2":
            print("\n--- Rent a Car ---")
            reg = input("Enter the registration of the car to rent: ")
            agency.rent_car(reg)

        elif choice == "3":
            print("\n--- Return a Car ---")
            reg = input("Enter the registration of the car to return: ")
            agency.return_car(reg)

        elif choice == "4":
            agency.display_available_cars()

        elif choice == "5":
            print("\nThank you for using the Fleet Management System. Goodbye!")
            break
        else:
            print("\n Invalid choice. Please enter a number between 1 and 5.")


if __name__ == "__main__":
    main()
